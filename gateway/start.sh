#!/bin/sh
set -eu

cat > /tmp/litellm.config.yaml <<EOF
model_list:
  - model_name: claude-sonnet
    litellm_params:
      model: bedrock/${BEDROCK_MODEL_CLAUDE_SONNET_ID}
  - model_name: claude-haiku
    litellm_params:
      model: bedrock/${BEDROCK_MODEL_CLAUDE_HAIKU_ID}

general_settings:
  master_key: ${LITELLM_MASTER_KEY}
  database_url: ${DATABASE_URL}
  store_model_in_db: true

litellm_settings:
  set_verbose: true
  drop_params: true
  request_timeout: 600
  cache: false
EOF

exec litellm --config /tmp/litellm.config.yaml --port 4000 --detailed_debug
