# Ingest Service (Producer)
This ingest service, i.e., the producer service implements the functionalities to interact with the messaging broker, i.e., RabbitMQ in our case to publish the incoming request/data.

## Requirements
- Set the following environment variables for RabbitMQ. The data will be published on a exchange `ingest_message`.
  - RABBITMQ_USERNAME
  - RABBITMQ_PASSWORD
  - RABBITMQ_URL, i.e., the hostname, by default it is localhost
  - RABBITMQ_PORT, by default 5672 is used
  - RABBITMQ_VHOST, default vhost is "/"
  - 

## Features Implemented
- [x] Logging  
- 
## Features to be Implemented
- [ ] Containerization of the application
- [ ] JWT-based Authentication
- [ ] E-mail confirmation for new JWT-user





### Acknowledgements
Special thanks to the authors of the resources below who helped with some best practices.
- Building Python Microservices with FastAPI
- Mastering-REST-APIs-with-FastAPI
- FastAPI official documentation

### License
[MIT](https://github.com/git/git-scm.com/blob/main/MIT-LICENSE.txt)