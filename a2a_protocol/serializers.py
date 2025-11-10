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
    """
    REVISED: Validates the 'parts' of a message. It now allows for 'text' or 'data' kinds.
    """
    kind = serializers.ChoiceField(choices=["text", "data"])
    text = serializers.CharField(required=False, allow_blank=True)
    data = serializers.JSONField(required=False) # 'data' can be any valid JSON (e.g., a list of messages)

class A2AMessageSerializer(serializers.Serializer):
    """Validates the main message object."""
    role = serializers.ChoiceField(choices=["user"])
    parts = MessagePartSerializer(many=True, min_length=1)
    # Adding metadata field as observed in the Telex request
    metadata = serializers.JSONField(required=False)
    messageId = serializers.CharField(required=False, allow_blank=True)


class PushNotificationConfigSerializer(serializers.Serializer):
    """
    Validates the webhook configuration. The URL is the most critical part,
    as it tells our agent where to send the final response.
    """
    url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    token = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    # Adding authentication field as observed in the Telex request
    authentication = serializers.JSONField(required=False)

class MessageConfigurationSerializer(serializers.Serializer):
    """Validates the overall message configuration."""
    # REVISED: 'blocking' can now be true or false.
    blocking = serializers.BooleanField(required=False, default=True)
    # The pushNotificationConfig is now optional.
    pushNotificationConfig = PushNotificationConfigSerializer(required=False, allow_null=True)
    # Adding other fields observed in the Telex request
    acceptedOutputModes = serializers.ListField(child=serializers.CharField(), required=False)
    historyLength = serializers.IntegerField(required=False)

class MessageParamsSerializer(serializers.Serializer):
    """Validates the 'params' block for a 'message/send' request."""
    message = A2AMessageSerializer()
    configuration = MessageConfigurationSerializer(required=False)
    
    # THE FINAL FIX: The taskId is not always sent by Telex, so it must be optional.
    taskId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    contextId = serializers.CharField(required=False, allow_null=True, allow_blank=True)


# --- Top-Level Request Serializer ---
class JSONRPCRequestSerializer(serializers.Serializer):
    """

    The top-level serializer that validates the entire incoming request body.
    """
    jsonrpc = serializers.CharField(required=True)
    id = serializers.CharField(required=True, help_text="The unique identifier for this specific request.")
    # REVISED: The method can be 'message/send' or other potential A2A methods.
    method = serializers.ChoiceField(choices=["message/send", "execute"]) 
    params = MessageParamsSerializer()

    def validate_jsonrpc(self, value):
        """
        Custom validation to ensure the JSON-RPC version field is exactly '2.0'.
        """
        if value != "2.0":
            logger.warning(f"Invalid JSON-RPC version received: '{value}'")
            raise serializers.ValidationError("The 'jsonrpc' version must be '2.0'.")
        return value