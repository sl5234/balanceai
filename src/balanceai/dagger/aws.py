import logging
from typing import Optional
import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.exceptions import ClientError, NoCredentialsError  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class AWSClients:
    """
    Container for all AWS service clients.

    Initializes AWS clients using boto3's default credential chain:
    - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - IAM roles (when running on EC2/ECS/Lambda)
    - AWS credentials file (~/.aws/credentials)
    - etc.

    No credentials are stored in this class - boto3 handles credential resolution.
    """

    def __init__(self, region_name: Optional[str] = None):
        """
        Initialize AWS clients container.

        Args:
            region_name: AWS region name (e.g., 'us-east-1'). If None, uses default region.
        """
        self.region_name = region_name
        self.s3_client: Optional[BaseClient] = None
        self.kms_client: Optional[BaseClient] = None
        self.bedrock_runtime_client: Optional[BaseClient] = None
        self._initialized = False

    def initialize(self) -> None:
        """
        Initialize all AWS service clients.

        Uses boto3's default credential chain to authenticate.
        Credentials are resolved from environment variables, IAM roles, or credential files.

        Raises:
            NoCredentialsError: If AWS credentials cannot be found
            ClientError: If there's an error initializing clients
        """
        if self._initialized:
            logger.warning("AWS clients already initialized")
            return

        try:
            logger.info("Initializing AWS clients...")

            self.s3_client = boto3.client("s3", region_name=self.region_name)
            logger.info("S3 client initialized")

            self.kms_client = boto3.client("kms", region_name=self.region_name)
            logger.info("KMS client initialized")

            self.bedrock_runtime_client = boto3.client(
                "bedrock-runtime", region_name=self.region_name
            )
            logger.info("Bedrock Runtime client initialized")

            self._initialized = True
            logger.info("All AWS clients initialized successfully")

        except NoCredentialsError:
            logger.error(
                "AWS credentials not found. Please configure credentials via environment variables, IAM role, or credential files."
            )
            raise
        except ClientError as e:
            logger.error(f"Error initializing AWS clients: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error initializing AWS clients: {e}")
            raise

    def is_initialized(self) -> bool:
        """Check if AWS clients have been initialized."""
        return self._initialized

    def get_s3_client(self) -> BaseClient:
        """
        Get S3 client.

        Returns:
            boto3 S3 client

        Raises:
            RuntimeError: If clients have not been initialized
        """
        if not self._initialized:
            raise RuntimeError("AWS clients have not been initialized. Call initialize() first.")
        return self.s3_client

    def get_kms_client(self) -> BaseClient:
        """
        Get KMS (Key Management Service) client.

        Returns:
            boto3 KMS client

        Raises:
            RuntimeError: If clients have not been initialized
        """
        if not self._initialized:
            raise RuntimeError("AWS clients have not been initialized. Call initialize() first.")
        return self.kms_client

    def get_bedrock_runtime_client(self) -> BaseClient:
        """
        Get Bedrock Runtime client.

        Returns:
            boto3 Bedrock Runtime client

        Raises:
            RuntimeError: If clients have not been initialized
        """
        if not self._initialized:
            raise RuntimeError("AWS clients have not been initialized. Call initialize() first.")
        return self.bedrock_runtime_client
