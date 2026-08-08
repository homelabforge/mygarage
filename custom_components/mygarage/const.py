"""Constants for the MyGarage Home Assistant integration."""

DOMAIN = "mygarage"
DEFAULT_HOST = "http://local-mygarage:8686"
DEFAULT_SCAN_INTERVAL = 60

CONF_HOST = "host"
CONF_API_KEY = "api_key"
CONF_WEBHOOK_TOKEN = "webhook_token"

EVENT_DUE_SOON = "mygarage.due_soon"
EVENT_OVERDUE = "mygarage.overdue"

ATTR_VIN = "vin"
ATTR_VEHICLE_NAME = "vehicle_name"
ATTR_OVERDUE = "overdue_maintenance"
ATTR_UPCOMING = "upcoming_maintenance"
