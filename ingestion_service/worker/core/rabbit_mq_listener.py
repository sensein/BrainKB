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

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set to DEBUG level to capture all logs

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
            blocked_connection_timeout=500
        )
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

def callback(ch, method, properties, body):
    """Callback function to handle messages from RabbitMQ."""
    logger.info(f"Received message with delivery tag: {method.delivery_tag}")
    logger.debug(f"Message properties: {properties}")
    
    try:
        req_type = json.loads(body)
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

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode message {method.delivery_tag}: {str(e)}")
        logger.debug(f"Raw message content: {body}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    except requests.RequestException as e:
        logger.error(f"HTTP request failed for message {method.delivery_tag}: {str(e)}")
        logger.debug(f"Request error details: {type(e).__name__}: {str(e)}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
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


