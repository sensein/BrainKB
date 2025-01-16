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
import json

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : configure_rabbit_mq.py
# @Software: PyCharm


from core.configuration import load_environment
from fastapi.responses import JSONResponse
import logging
import pika

# Load environment variables

logger = logging.getLogger(__name__)

# Retrieve username and password from environment
rabbitmq_username = load_environment()["RABBITMQ_USERNAME"]
rabbitmq_password = load_environment()["RABBITMQ_PASSWORD"]
rabbitmq_url = load_environment()["RABBITMQ_URL"]
rabbitmq_port = load_environment()["RABBITMQ_PORT"]
rabbitmq_vhost = load_environment()["RABBITMQ_VHOST"]



def connect_to_rabbitmq():
    credentials = pika.PlainCredentials(rabbitmq_username, rabbitmq_password)

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(rabbitmq_url, rabbitmq_port, rabbitmq_vhost, credentials)
    )
    channel = connection.channel()
    return connection, channel


def publish_message(message, exchange_name="ingest_message_direct"):
    """Publish a message to a fanout exchange in RabbitMQ, meaning, there will be multiple consumers (or subscribers)
    for the same mesage."""
    connection, channel = connect_to_rabbitmq()
    channel.exchange_declare(exchange=exchange_name, durable=True)
    try:
        # print(f"message to publish {message}")
        channel.basic_publish(exchange=exchange_name,
                              routing_key='brainkb',  # Routing key is ignored by fanout exchanges
                              body=message,
                              properties=pika.BasicProperties(
                                  delivery_mode=2,  # Make message persistent
                              ))
    except Exception as e:
        logger.info(f"Publisher '{exchange_name}': {e} {rabbitmq_port} {rabbitmq_url} {rabbitmq_vhost}")

        return JSONResponse(content={"message": "Error occured. Please contact administrator"})
    logger.info(f"Published message to exchange '{exchange_name}': {message}")

    channel.close()
    connection.close()

