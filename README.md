# WLANPi RXG Agent

## Development Endpoints

### Development Shutdown

The application provides a `/dev_shutdown` endpoint for graceful shutdown during development. This endpoint exists because certain IDEs send a SIGKILL signal before the application has time to clean up resources properly.

**Usage:**
```bash
curl -X POST http://localhost:8200/dev_shutdown \
  -H "Content-Type: application/json" \
  -d '{"CONFIRM": 1}'
```

**Response:**
- When `CONFIRM` is set to 1: Sends SIGTERM to the application process for graceful shutdown
- When `CONFIRM` is not 1: Returns message requiring confirmation

This allows proper cleanup of network interfaces, DHCP clients, and other system resources before termination.