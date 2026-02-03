ARG MAGE_VERSION=latest
FROM mageai/mageai:${MAGE_VERSION}

ARG PROJECT_NAME=mage_project
ARG USER_CODE_PATH=/home/src/${PROJECT_NAME}

# NOTE: This can overwrite the project requirements.txt on first run.
COPY requirements.txt ${USER_CODE_PATH}/requirements.txt

RUN pip3 install -r ${USER_CODE_PATH}/requirements.txt
