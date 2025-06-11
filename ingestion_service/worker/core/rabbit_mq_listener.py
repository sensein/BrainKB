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
from core.configuration import load_environment
from core.shared import get_endpoints
import requests
from core.shared import attach_provenance
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

logger = logging.getLogger(__name__)
def connect_to_rabbitmq():
    """Connect to RabbitMQ"""
    logger.info("###### Connect to RabbitMQ ######")
    credentials = pika.PlainCredentials(rabbitmq_username, rabbitmq_password)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(rabbitmq_url, rabbitmq_port, rabbitmq_vhost, credentials)
    )
    channel = connection.channel()
    return connection, channel


def callback(ch, method, properties, body):
    """Callback function to handle messages from RabbitMQ."""
    logger.info("###### Received!! ######")
    req_type = json.loads(body)
    logger.info(f"###### Received data before attaching provenance - {req_type}")


    # the ingested data comes in TTL, particularly, the json-ld and ttl data
    if req_type["data_type"] == "ttl":
        ttl_data_with_provenance = attach_provenance(user=req_type["user"],
                                                 ttl_data=req_type["kg_data"]
                                                 )
        kg_data_for_req = {"kg_data":ttl_data_with_provenance,
                           "named_graph_iri":req_type["named_graph"],
                           "type": req_type["data_type"]}

        logger.info(f"###### After adding ingestion provenance - {kg_data_for_req}")
        if isinstance(kg_data_for_req, dict):
            kg_data_for_req = json.dumps(kg_data_for_req)
        logger.info(f"###### Sending data to QueryService to insert into the database - {kg_data_for_req}  ######")
        credentials={
            "email": jwt_username,
            "password": jwt_password
        }

        login_response =  requests.post(bearer_token_url, json=credentials)

        login_response.raise_for_status()

        access_token = login_response.json().get("access_token")
    
        req = requests.post(ingest_url, data=kg_data_for_req, headers={"Content-Type": "application/json",
                                                                       "Authorization": f"Bearer {access_token}"
                                                                       })

        logger.info(req.status_code, req.text)
        if req.status_code == 200 and json.loads(req.text)["status"] == "success": 
            # Successful acknowledgment
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info("###### Acknowledging the RabbitMQ queue that the message in the queue has been processed ###### ")


def start_consuming(exchange_name='ingest_message_direct', routing_key='brainkb'):
    logger.info("###### Starting the RabbitMQ consumer ######")
    connection, channel = connect_to_rabbitmq()
    channel.exchange_declare(exchange=exchange_name, exchange_type='direct',durable=True)
    result = channel.queue_declare(queue='', exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=routing_key)

    channel.basic_consume(
        queue=queue_name, on_message_callback=callback, auto_ack=False)

    print('[*] Waiting for messages. To exit press CTRL+C')

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        channel.close()
        connection.close()


