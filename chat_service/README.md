# ML Service
This microserivce provides an API endpoint 
## Requirements
- Set the following environment variables for RabbitMQ. The data will be published on a exchange `ingest_message`.
  - RABBITMQ_USERNAME
  - RABBITMQ_PASSWORD
  - RABBITMQ_URL, i.e., the hostname, by default it is localhost
  - RABBITMQ_PORT, by default 5672 is used
  - RABBITMQ_VHOST, default vhost is "/"
  - 
 





### Acknowledgements
Special thanks to the authors of the resources below who helped with some best practices.
- Building Python Microservices with FastAPI
- Mastering-REST-APIs-with-FastAPI
- FastAPI official documentation

### License
[MIT](https://github.com/git/git-scm.com/blob/main/MIT-LICENSE.txt)