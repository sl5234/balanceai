import base64
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from appdevcommons.kms_encryptor import KMSEncryptor  # type: ignore[import-untyped]
from balanceai.dagger.aws import AWSClients


class Settings(BaseSettings):
    """
    Application settings.

    AWS credentials are NOT stored here - they are resolved by boto3 from:
    - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - IAM roles (when running on EC2/ECS/Lambda)
    - AWS credentials file (~/.aws/credentials)
    """

    # AWS KMS
    kms_key_arn: str = "arn:aws:kms:us-west-2:792341830430:key/f46115bb-774a-4777-ab66-29903da24381"

    encrypted_plaid_api_token: str = (
        "AQICAHg7rDJp72oZrIfl2vnBxkvlcidlgcJm7juguFV/iuWU+AEppUF7FLTz2DaUQy+zza2kAAAAfjB8BgkqhkiG9w0BBwagbzBtAgEAMGgGCSqGSIb3DQEHATAeBglghkgBZQMEAS4wEQQMORXUzcZf2KGd03SAAgEQgDueiST/NvgyT7IC3mlwlwxLBMyJPcIze+Yq8pNCtWKF61RG7G3xCdt1q7BgJWBlfzTt4XXVPDU84hU12g=="
    )

    encrypted_gemini_api_key: str = (
        "AQICAHg7rDJp72oZrIfl2vnBxkvlcidlgcJm7juguFV/iuWU+AEV3H++a4lvm7YgbGSkh4ZoAAAAhjCBgwYJKoZIhvcNAQcGoHYwdAIBADBvBgkqhkiG9w0BBwEwHgYJYIZIAWUDBAEuMBEEDHFXBeKWFqtCVn6LowIBEIBC+dNo4VUUtu4Txd1SSjSOs/laMm9xuXLALC4WKe88kzuIgmaOEFpYrFCn/YkfSOjHAVEnwhPfW+lXIPKB75xErGqn"
    )

    encrypted_openai_api_key: str = (
        "AQICAHg7rDJp72oZrIfl2vnBxkvlcidlgcJm7juguFV/iuWU+AEdbatti8JQNFOug7gUoSKpAAABCDCCAQQGCSqGSIb3DQEHBqCB9jCB8wIBADCB7QYJKoZIhvcNAQcBMB4GCWCGSAFlAwQBLjARBAzsgIXyaMSi8csf0K8CARCAgb8rm+S9FMXw5wvKUGcQqbiNuhk9P9CH1btdSqVwSEnUqYDZIMZS6Kk9U4hINowfWZdOZChAb2pm2oHF+3CoQ/535V1EHYy5Uv9YaP2gwrQ3hFklAZZhbPEkjUp5ddmT40nQZShmOypFmA/yfIds2eaheYG7aG9q47KLdhqm6qv6hbTLa+jR7TVylVNjYeInq+FhrHpJJc5cEsjsDmT5OhUXlSk9nOCPMjrs4hMkYWAFVpqJSsd4BF5RaTMwn2dwqg=="
    )

    _aws_clients: Optional[AWSClients] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields from environment variables
    )

    def set_aws_clients(self, aws_clients: AWSClients) -> None:
        """Set AWS clients instance for decryption."""
        self._aws_clients = aws_clients

    @staticmethod
    def decrypt_value(encrypted_value: str, aws_clients: AWSClients, kms_key_arn: str) -> str:
        """
        Decrypt a value using AWS KMS via KMSEncryptor from appdevcommons.

        Args:
            encrypted_value: Base64-encoded encrypted value (CiphertextBlob as string)
            aws_clients: Initialized AWSClients instance
            kms_key_arn: KMS key ARN to use for decryption

        Returns:
            Decrypted plaintext value as string
        """
        kms_client = aws_clients.get_kms_client()

        # Decode the base64-encoded ciphertext string to bytes
        ciphertext_blob = base64.b64decode(encrypted_value)

        # Decrypt using KMSEncryptor
        plaintext_bytes = KMSEncryptor.decrypt(
            ciphertext=ciphertext_blob, kms_key_arn=kms_key_arn, kms_client=kms_client
        )

        # Decode bytes to string
        return plaintext_bytes.decode("utf-8")

    @property
    def plaid_api_token(self) -> str:
        """Decrypted Toggl API token."""
        assert self._aws_clients is not None, "AWS clients must be initialized"
        return self.decrypt_value(
            self.encrypted_plaid_api_token, self._aws_clients, self.kms_key_arn
        )

    @property
    def gemini_api_key(self) -> str:
        """Decrypted Gemini API key."""
        assert self._aws_clients is not None, "AWS clients must be initialized"
        return self.decrypt_value(
            self.encrypted_gemini_api_key, self._aws_clients, self.kms_key_arn
        )

    @property
    def openai_api_key(self) -> str:
        """Decrypted OpenAI API key."""
        assert self._aws_clients is not None, "AWS clients must be initialized"
        return self.decrypt_value(
            self.encrypted_openai_api_key, self._aws_clients, self.kms_key_arn
        )


settings = Settings()
