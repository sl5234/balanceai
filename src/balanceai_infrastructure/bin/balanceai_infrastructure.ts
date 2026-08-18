#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { BalanceAiService } from '../lib/balanceai_service_stack';

const app = new cdk.App();
new BalanceAiService(app, 'BalanceaiInfrastructureStack', {
  // Populated by the CDK CLI from your resolved AWS credentials/region — set
  // AWS_REGION=us-west-2 in your shell (or on the AWS profile you use here),
  // since this project intentionally targets us-west-2, not the account's
  // default CLI region.
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },
});
