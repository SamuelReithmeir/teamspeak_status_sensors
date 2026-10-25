"""Constants for the TeamSpeak Server Info integration."""

DOMAIN = "samuelre_teamspeak"

# Configuration keys
CONF_SERVER_ID = "server_id"
CONF_API_KEY = "api_key"

# Default values
DEFAULT_PORT = 10080
DEFAULT_SERVER_ID = 1
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 5

# Options
CONF_USERS = "users"
CONF_USER_DB_ID = "db_id"
CONF_USER_UID = "uid"
CONF_USER_NAME = "name"

# The web query runs on a single server thread: keep request volume low.
# Slow data (clientdblist, channellist) is refreshed at most this often.
SLOW_REFRESH_INTERVAL = 300  # seconds
MAX_BACKOFF_INTERVAL = 900  # seconds, upper bound for the poll interval on failure

# Prefix of the online binary sensor entity id (binary_sensor.tsonline_<name>)
ONLINE_OBJECT_ID_PREFIX = "tsonline_"

CLIENT_TYPE_USER = "0"
CLIENT_TYPE_QUERY = "1"
