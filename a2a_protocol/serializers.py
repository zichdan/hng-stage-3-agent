# a2a_protocol/serializers.py
import logging
from rest_framework import serializers

# Get a logger instance for this module
logger = logging.getLogger('a2a_protocol')

# ==============================================================================
# A2A PROTOCOL SERIALIZERS
# ==============================================================================
# These serializers define the expected structure of an incoming JSON-RPC 2.0
# request from a platform like Telex.im. By defining this structure, we gain
# powerful, automatic validation for every request. If a request is malformed,

# our API will automatically return a 400 Bad Request with details on what's wrong.
# ==============================================================================

class MessagePartSerializer(serializers.Serializer):
    """Validates the 'parts' of a message, ensuring it's text-based."""
    kind = serializers.ChoiceField(choices=["text"])
    text = serializers.CharField(allow_blank=False, trim_whitespace=True)

class A2AMessageSerializer(serializers.Serializer):
    """Validates the main message object."""
    role = serializers.ChoiceField(choices=["user"])
    parts = MessagePartSerializer(many=True, min_length=1)

class PushNotificationConfigSerializer(serializers.Serializer):
    """
    Validates the webhook configuration. The URL is the most critical part,
    as it tells our agent where to send the final response.
    """
    url = serializers.URLField()
    token = serializers.CharField(required=False, allow_null=True, allow_blank=True)

class MessageConfigurationSerializer(serializers.Serializer):
    """Validates the overall message configuration."""
    # We expect 'blocking' to be false for our async architecture.
    blocking = serializers.BooleanField(default=False)
    pushNotificationConfig = PushNotificationConfigSerializer()

class MessageParamsSerializer(serializers.Serializer):
    """Validates the 'params' block of the JSON-RPC request."""
    message = A2AMessageSerializer()
    configuration = MessageConfigurationSerializer()
    
    # These are crucial for tracking the request and conversation state.
    taskId = serializers.CharField() # The unique ID for this specific task
    contextId = serializers.CharField(required=False, allow_null=True, allow_blank=True)


# --- Top-Level Request Serializer ---
class JSONRPCRequestSerializer(serializers.Serializer):
    """

    The top-level serializer that validates the entire incoming request body.
    """
    jsonrpc = serializers.CharField(required=True)
    id = serializers.CharField(required=True, help_text="The unique identifier for this specific request.")
    method = serializers.ChoiceField(choices=["message/send"])
    params = MessageParamsSerializer()

    def validate_jsonrpc(self, value):
        """
        Custom validation to ensure the JSON-RPC version field is exactly '2.0'.
        """
        if value != "2.0":
            logger.warning(f"Invalid JSON-RPC version received: '{value}'")
            raise serializers.ValidationError("The 'jsonrpc' version must be '2.0'.")
        return value