# AWS Lambda Python 3.12 base (Amazon Linux 2023). Brings the Lambda runtime + boto3.
FROM public.ecr.aws/lambda/python:3.12

# The whole point: git, so the handler can clone a repo URL at runtime.
RUN microdnf install -y git && microdnf clean all

# Runtime deps (boto3 is already in the base image).
RUN pip install --no-cache-dir numpy google-genai groq

# App + handler code into the Lambda task root.
COPY app ${LAMBDA_TASK_ROOT}/app
COPY handlers ${LAMBDA_TASK_ROOT}/handlers

# Handler entrypoint (module.function).
CMD ["handlers.ingest_handler.handler"]
