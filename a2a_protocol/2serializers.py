# a2a_protocol/serializers.py
import logging
from rest_framework import serializers

logger = logging.getLogger('a2a_protocol')

# --- Nested Serializers for the A2A Protocol Structure ---
# We use nested serializers to cleanly validate the complex JSON object.

class _MessagePartSerializer(serializers.Serializer):
    """Validates a single 'part' of a message."""
    kind = serializers.ChoiceField(choices=["text"])
    text = serializers.CharField(trim_whitespace=True)

class _MessageSerializer(serializers.Serializer):
    """Validates the main 'message' object."""
    role = serializers.ChoiceField(choices=["user"])
    parts = _MessagePartSerializer(many=True, min_length=1)

class _PushNotificationConfigSerializer(serializers.Serializer):
    """Validates the webhook configuration for sending the response back."""
    url = serializers.URLField()
    token = serializers.CharField(required=False, allow_blank=True, allow_null=True)

class _ConfigurationSerializer(serializers.Serializer):
    """Validates the 'configuration' object."""
    pushNotificationConfig = _PushNotificationConfigSerializer()

class _ParamsSerializer(serializers.Serializer):
    """Validates the main 'params' object containing all the details."""
    message = _MessageSerializer()
    configuration = _ConfigurationSerializer()
    contextId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    taskId = serializers.CharField() # The unique ID for this specific task

# --- Top-Level Request Serializer ---
class A2ARequestSerializer(serializers.Serializer):
    """
    The main serializer for validating the entire incoming JSON-RPC 2.0 request
    from the Telex.im platform.
    """
    jsonrpc = serializers.CharField()
    id = serializers.CharField() # The overall request ID
    method = serializers.ChoiceField(choices=["message/send"])
    params = _ParamsSerializer()

    def validate_jsonrpc(self, value):
        """Custom validation to ensure the JSON-RPC version is '2.0'."""
        if value != "2.0":
            logger.warning(f"Invalid jsonrpc version received: {value}")
            raise serializers.ValidationError("The 'jsonrpc' version must be '2.0'.")
        return value