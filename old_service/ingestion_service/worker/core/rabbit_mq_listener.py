# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : rabbit_mq_listener.py
# @Software: PyCharm

import json
import pika
import logging
import time
from pika.exceptions import AMQPConnectionError, ChannelWrongStateError, ConnectionWrongStateError
from core.configuration import load_environment
from core.shared import get_endpoints
import requests
from core.shared import attach_provenance
from collections import defaultdict
import threading

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set to DEBUG level to capture all logs

# Message size limits (in bytes)
MAX_MESSAGE_SIZE = int(1.4 * 1024 * 1024 * 1024)  # 1.4GB maximum frame size
MAX_TTL_SIZE = int(1.4 * 1024 * 1024 * 1024)     # 1.4GB maximum frame size
MAX_FRAME_SIZE = int(1.5 * 1024 * 1024 * 1024)  # 1.5GB maximum frame size

# Chunk handling configuration
CHUNK_TIMEOUT = 300  # 5 minutes timeout for chunk reassembly
CHUNK_CLEANUP_INTERVAL = 60  # 1 minute cleanup interval

# Retrieve username and password from environment
rabbitmq_username = load_environment()["RABBITMQ_USERNAME"]
rabbitmq_password = load_environment()["RABBITMQ_PASSWORD"]
rabbitmq_url = load_environment()["RABBITMQ_URL"]
rabbitmq_port = load_environment()["RABBITMQ_PORT"]
rabbitmq_vhost = load_environment()["RABBITMQ_VHOST"]
ingest_url = load_environment()["INGEST_URL"]
jwt_password = load_environment()["JWT_LOGIN_PASSWORD"]
bearer_token_url = load_environment()["JWT_BEARER_TOKEN_URL"]
jwt_username = load_environment()["JWT_LOGIN_EMAIL"]

logger.info("Initializing RabbitMQ connection parameters")
logger.debug(f"RabbitMQ URL: {rabbitmq_url}, Port: {rabbitmq_port}, VHost: {rabbitmq_vhost}")
logger.info(f"Message size limits - Max message: {MAX_MESSAGE_SIZE/1024/1024/1024:.1f}GB, Max TTL: {MAX_TTL_SIZE/1024/1024/1024:.1f}GB, Max frame: {MAX_FRAME_SIZE/1024/1024/1024:.1f}GB")

class ChunkManager:
    def __init__(self):
        logger.info("Initializing ChunkManager for handling large messages")
        self.chunks = defaultdict(dict)
        self.metadata = {}
        self.timestamps = {}
        self.lock = threading.Lock()
        self.cleanup_thread = threading.Thread(target=self._cleanup_old_chunks, daemon=True)
        self.cleanup_thread.start()
        logger.debug("ChunkManager initialized with cleanup thread")

    def add_chunk(self, message_id, chunk_index, chunk_data, total_chunks, metadata=None):
        with self.lock:
            if metadata:
                logger.info(f"Adding metadata for message {message_id}: {metadata}")
                self.metadata[message_id] = metadata
            chunk_size = len(chunk_data)
            logger.info(f"Adding chunk {chunk_index + 1}/{total_chunks} for message {message_id} (size: {chunk_size/1024/1024:.2f}MB)")
            self.chunks[message_id][chunk_index] = chunk_data
            self.timestamps[message_id] = time.time()
            logger.debug(f"Current progress for message {message_id}: {len(self.chunks[message_id])}/{total_chunks} chunks received")

    def is_complete(self, message_id):
        with self.lock:
            if message_id not in self.metadata:
                logger.debug(f"Message {message_id} metadata not found")
                return False
            metadata = self.metadata[message_id]
            is_complete = len(self.chunks[message_id]) == metadata['total_chunks']
            if is_complete:
                logger.info(f"Message {message_id} is complete with all {metadata['total_chunks']} chunks")
            return is_complete

    def get_complete_message(self, message_id):
        with self.lock:
            if not self.is_complete(message_id):
                logger.warning(f"Attempted to get incomplete message {message_id}")
                return None
            
            logger.info(f"Starting assembly of message {message_id}")
            # Sort chunks by index and combine
            chunk_list = [self.chunks[message_id][i] for i in range(len(self.chunks[message_id]))]
            complete_message = b''.join(chunk_list)
            total_size = len(complete_message)
            logger.info(f"Successfully assembled message {message_id} (total size: {total_size/1024/1024:.2f}MB)")
            
            # Clean up
            logger.debug(f"Cleaning up chunks for message {message_id}")
            del self.chunks[message_id]
            del self.metadata[message_id]
            del self.timestamps[message_id]
            
            return complete_message

    def _cleanup_old_chunks(self):
        while True:
            time.sleep(CHUNK_CLEANUP_INTERVAL)
            current_time = time.time()
            with self.lock:
                for message_id in list(self.timestamps.keys()):
                    if current_time - self.timestamps[message_id] > CHUNK_TIMEOUT:
                        logger.warning(f"Cleaning up timed out chunks for message {message_id} (age: {current_time - self.timestamps[message_id]:.0f}s)")
                        del self.chunks[message_id]
                        del self.metadata[message_id]
                        del self.timestamps[message_id]

class RabbitMQConnection:
    def __init__(self):
        logger.info("Initializing RabbitMQConnection class")
        self.connection = None
        self.channel = None
        self.should_reconnect = True
        self.reconnect_delay = 0
        self.max_reconnect_delay = 30
        self.credentials = pika.PlainCredentials(rabbitmq_username, rabbitmq_password)
        self.parameters = pika.ConnectionParameters(
            host=rabbitmq_url,
            port=rabbitmq_port,
            virtual_host=rabbitmq_vhost,
            credentials=self.credentials,
            heartbeat=600,
            blocked_connection_timeout=500,
            frame_max=MAX_FRAME_SIZE  # Set maximum frame size to 1.5GB
        )
        self.chunk_manager = ChunkManager()
        logger.debug("Connection parameters configured with heartbeat=600 and blocked_connection_timeout=500")

    def connect(self):
        """Establish connection to RabbitMQ with retry logic"""
        logger.info("Starting RabbitMQ connection process")
        while self.should_reconnect:
            try:
                if self.connection is None or self.connection.is_closed:
                    logger.info(f"Attempting to connect to RabbitMQ (attempt delay: {self.reconnect_delay}s)...")
                    logger.debug(f"Connection state - Connection: {'None' if self.connection is None else 'Closed' if self.connection.is_closed else 'Open'}")
                    
                    self.connection = pika.BlockingConnection(self.parameters)
                    self.channel = self.connection.channel()
                    self.reconnect_delay = 0
                    
                    logger.info("Successfully connected to RabbitMQ")
                    logger.debug(f"Channel state: {'Open' if self.channel.is_open else 'Closed'}")
                    return True
            except (AMQPConnectionError, ConnectionWrongStateError) as e:
                self.reconnect_delay = min(self.reconnect_delay + 5, self.max_reconnect_delay)
                logger.error(f"Connection failed: {str(e)}. Retrying in {self.reconnect_delay} seconds...")
                logger.debug(f"Connection error details: {type(e).__name__}: {str(e)}")
                time.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error(f"Unexpected error during connection: {str(e)}")
                logger.debug(f"Unexpected error details: {type(e).__name__}: {str(e)}")
                time.sleep(5)
        logger.warning("Connection attempts stopped due to should_reconnect=False")
        return False

    def close(self):
        """Safely close the connection"""
        logger.info("Initiating connection closure")
        self.should_reconnect = False
        try:
            if self.channel and self.channel.is_open:
                logger.debug("Closing channel")
                self.channel.close()
            if self.connection and self.connection.is_open:
                logger.debug("Closing connection")
                self.connection.close()
            logger.info("Connection and channel closed successfully")
        except Exception as e:
            logger.error(f"Error while closing connection: {str(e)}")
            logger.debug(f"Close error details: {type(e).__name__}: {str(e)}")

def check_message_size(body, message_type="ttl"):
    """Check if message size is within limits"""
    message_size = len(body)
    max_size = MAX_TTL_SIZE if message_type == "ttl" else MAX_MESSAGE_SIZE
    
    logger.debug(f"Message size: {message_size/1024/1024:.2f}MB, Max allowed: {max_size/1024/1024:.2f}MB")
    
    if message_size > max_size:
        raise ValueError(f"Message size {message_size/1024/1024:.2f}MB exceeds maximum allowed size of {max_size/1024/1024:.2f}MB")
    return True

def process_message(message_data, ch, method):
    """Process a complete message (either reassembled or single)."""
    try:
        logger.info(f"Processing complete message (size: {len(message_data)/1024/1024:.2f}MB)")
        req_type = json.loads(message_data)
        logger.info(f"Processing message of type: {req_type.get('data_type', 'unknown')}")
        logger.debug(f"Message content: {req_type}")

        if req_type["data_type"] == "ttl":
            logger.info("Processing TTL data")
            ttl_data_with_provenance = attach_provenance(
                user=req_type["user"],
                ttl_data=req_type["kg_data"]
            )
            logger.debug("Provenance attached successfully")
            
            kg_data_for_req = {
                "kg_data": ttl_data_with_provenance,
                "named_graph_iri": req_type["named_graph"],
                "type": req_type["data_type"]
            }

            logger.info("Preparing to send data to QueryService")
            if isinstance(kg_data_for_req, dict):
                kg_data_for_req = json.dumps(kg_data_for_req)
                logger.debug("Converted kg_data_for_req to JSON string")

            logger.info("Authenticating with JWT")
            credentials = {
                "email": jwt_username,
                "password": jwt_password
            }

            login_response = requests.post(bearer_token_url, json=credentials)
            login_response.raise_for_status()
            logger.debug("JWT authentication successful")

            access_token = login_response.json().get("access_token")
            logger.info("Sending data to ingest service")
            
            req = requests.post(
                ingest_url,
                data=kg_data_for_req,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}"
                }
            )

            logger.info(f"Received response from ingest service - Status: {req.status_code}")
            logger.debug(f"Response content: {req.text}")

            if req.status_code == 200 and json.loads(req.text)["status"] == "success":
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.info(f"Message {method.delivery_tag} successfully processed and acknowledged")
            else:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                logger.error(f"Failed to process message {method.delivery_tag}: {req.text}")

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

def callback(ch, method, properties, body):
    """Callback function to handle messages from RabbitMQ."""
    logger.info(f"Received message with delivery tag: {method.delivery_tag}")
    logger.debug(f"Message properties: {properties}")
    
    try:
        # Check message type from headers
        message_type = properties.headers.get('message_type', 'complete')
        
        if message_type == 'metadata':
            # Handle metadata message
            metadata = json.loads(body)
            logger.info(f"Received metadata for chunked message: {metadata}")
            logger.debug(f"Message will be split into {metadata['total_chunks']} chunks of {metadata['chunk_size']/1024/1024:.2f}MB each")
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        elif message_type == 'chunk':
            # Handle chunk message
            chunk_index = properties.headers.get('chunk_index')
            total_chunks = properties.headers.get('total_chunks')
            message_id = properties.message_id
            
            logger.info(f"Received chunk {chunk_index + 1}/{total_chunks} for message {message_id} (size: {len(body)/1024/1024:.2f}MB)")
            
            # Add chunk to manager
            ch.connection.chunk_manager.add_chunk(
                message_id,
                chunk_index,
                body,
                total_chunks
            )
            
            # Check if we have all chunks
            if ch.connection.chunk_manager.is_complete(message_id):
                logger.info(f"All chunks received for message {message_id}, starting reassembly")
                complete_message = ch.connection.chunk_manager.get_complete_message(message_id)
                if complete_message:
                    logger.info(f"Message {message_id} reassembly complete, starting processing")
                    process_message(complete_message, ch, method)
                else:
                    logger.error(f"Failed to reassemble message {message_id}")
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            else:
                # Acknowledge chunk receipt
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.debug(f"Chunk {chunk_index + 1}/{total_chunks} acknowledged, waiting for more chunks")
                
        else:
            # Handle complete (non-chunked) message
            logger.info(f"Processing non-chunked message (size: {len(body)/1024/1024:.2f}MB)")
            process_message(body, ch, method)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode message {method.delivery_tag}: {str(e)}")
        logger.debug(f"Raw message content: {body}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    except Exception as e:
        logger.error(f"Unexpected error processing message {method.delivery_tag}: {str(e)}")
        logger.debug(f"Error details: {type(e).__name__}: {str(e)}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

def start_consuming(exchange_name='ingest_message_direct', routing_key='brainkb'):
    """Start consuming messages with robust connection handling"""
    logger.info("Starting RabbitMQ consumer")
    logger.debug(f"Exchange: {exchange_name}, Routing key: {routing_key}")
    
    rabbitmq = RabbitMQConnection()
    
    while rabbitmq.should_reconnect:
        try:
            if not rabbitmq.connect():
                logger.warning("Connection failed, will retry...")
                continue

            channel = rabbitmq.channel
            logger.info("Setting up exchange and queue")
            channel.exchange_declare(exchange=exchange_name, exchange_type='direct', durable=True)
            result = channel.queue_declare(queue='', exclusive=True)
            queue_name = result.method.queue
            logger.debug(f"Created queue: {queue_name}")
            
            channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=routing_key)
            logger.debug(f"Queue {queue_name} bound to exchange {exchange_name} with routing key {routing_key}")

            # Set QoS prefetch count
            channel.basic_qos(prefetch_count=1)
            logger.debug("QoS prefetch count set to 1")
            
            channel.basic_consume(
                queue=queue_name,
                on_message_callback=callback,
                auto_ack=False
            )
            logger.info("Consumer started successfully")

            logger.info('[*] Waiting for messages. To exit press CTRL+C')
            channel.start_consuming()

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, initiating graceful shutdown...")
            rabbitmq.should_reconnect = False
            break
        except (AMQPConnectionError, ConnectionWrongStateError, ChannelWrongStateError) as e:
            logger.error(f"Connection error occurred: {str(e)}")
            logger.debug(f"Connection error details: {type(e).__name__}: {str(e)}")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            logger.debug(f"Error details: {type(e).__name__}: {str(e)}")
            time.sleep(5)
        finally:
            try:
                if rabbitmq.channel and rabbitmq.channel.is_open:
                    logger.debug("Stopping message consumption")
                    rabbitmq.channel.stop_consuming()
            except Exception as e:
                logger.error(f"Error while stopping consumption: {str(e)}")
                logger.debug(f"Stop consumption error details: {type(e).__name__}: {str(e)}")

    rabbitmq.close()
    logger.info("RabbitMQ consumer stopped")


