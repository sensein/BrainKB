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

# Retrieve username and password from environment
rabbitmq_username = load_environment()["RABBITMQ_USERNAME"]
rabbitmq_password = load_environment()["RABBITMQ_PASSWORD"]
rabbitmq_url = load_environment()["RABBITMQ_URL"]
rabbitmq_port = load_environment()["RABBITMQ_PORT"]
rabbitmq_vhost = load_environment()["RABBITMQ_VHOST"]

logger = logging.getLogger(__name__)
def connect_to_rabbitmq():
    credentials = pika.PlainCredentials(rabbitmq_username, rabbitmq_password)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(rabbitmq_url, rabbitmq_port, rabbitmq_vhost, credentials)
    )
    channel = connection.channel()
    return connection, channel


def callback(ch, method, properties, body):
    """Callback function to handle messages from RabbitMQ."""
    logger.info("###### Received!! ######")
    req_type = json.loads(body)["type"]
    _URL = get_endpoints(req_type)

    if req_type == "json" or req_type=="jsonld":
        req = requests.post(_URL, data=body, headers={"Content-Type": "application/json"})
        print(req.status_code)
    ch.basic_ack(delivery_tag=method.delivery_tag)
    print("Message processed and acknowledged")


def start_consuming(exchange_name='ingest_message'):
    connection, channel = connect_to_rabbitmq()
    channel.exchange_declare(exchange=exchange_name, exchange_type='fanout')
    result = channel.queue_declare(queue='', exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange=exchange_name, queue=queue_name)

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


