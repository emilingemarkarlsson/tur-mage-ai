ARG MAGE_VERSION=latest
FROM mageai/mageai:${MAGE_VERSION}

ARG PROJECT_NAME=mage_project
ARG USER_CODE_PATH=/home/src/${PROJECT_NAME}

# postgresql-client behövs för att kunna köra pg_dump från mage-containern
# (t.ex. vid backup av Mage-metadata eller för ad-hoc-access mot källdata).
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends postgresql-client-15 && \
    rm -rf /var/lib/apt/lists/*

# Installera Python-dependencies FÖRE koden kopieras in för bra layer-caching.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Kopiera in Mage-projektet och hjälpskript. mage_project/ måste hamna på
# USER_CODE_PATH för att mage ska hitta det. Vi kopierar även scripts/.
# OBS: state/ och data_lake/ är gitignored och kommer inte med.
COPY mage_project ${USER_CODE_PATH}
COPY scripts /home/src/scripts

# Säkerställ att pip-installerade requirements.txt också finns i projekt-dirn
# så Mage UI kan visa den (Mage läser den från USER_CODE_PATH vid uppstart).
COPY requirements.txt ${USER_CODE_PATH}/requirements.txt

WORKDIR /home/src
