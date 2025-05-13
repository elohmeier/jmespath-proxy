# JMESPath Proxy Demo

This directory contains a Docker Compose setup to demonstrate the JMESPath Proxy with Prometheus and Alertmanager.

## Components

- **Prometheus**: Monitors services and fires alerts based on defined rules
- **Alertmanager**: Receives alerts from Prometheus and forwards them to JMESPath Proxy
- **JMESPath Proxy**: Receives alerts, transforms them using JMESPath expressions, and forwards them
- **Echo Service**: Receives transformed alerts from JMESPath Proxy and prints them to stdout
- **Flapper**: A node-exporter instance that provides metrics that will trigger flapping alerts

## Usage

1. Start the demo:
   ```
   cd demo
   docker-compose up -d
   ```

2. Access the services:
   - Prometheus: http://localhost:9090
   - Alertmanager: http://localhost:9093
   - JMESPath Proxy: http://localhost:8000
   - Echo Service: http://localhost:8080

3. Test the JMESPath transformation:
   - Go to http://localhost:8000 and use the test interface
   - Try different JMESPath expressions on the alert data
   - Check the Echo Service logs to see the transformed alerts:
     ```
     docker logs echo-service
     ```

4. Modify the JMESPath expression:
   ```
   docker-compose down
   # Edit the JMESPATH_EXPRESSION in docker-compose.yml
   docker-compose up -d
   ```

## Example JMESPath Expressions

- `body`: Pass through all alerts unchanged
- `body[?labels.severity=='warning']`: Only forward warning alerts
- `body[*].{name: labels.alertname, severity: labels.severity}`: Extract only name and severity
- `body[*].{alert: labels.alertname, summary: annotations.summary, description: annotations.description}`: Format alerts with key information
