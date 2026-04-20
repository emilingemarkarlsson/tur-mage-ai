# Mage Notifications

Pipeline-fel och SLA-brott rapporteras automatiskt till Slack-kanalen
(samma webhook som används för `litellm-daily-spend` och andra boter).

## Aktivt just nu

| Kanal | Hur det triggras | Konfiguration |
|---|---|---|
| **Slack** | Pipeline failure + SLA breach | `mage_project/metadata.yaml` i containern |

Slack webhook: `hooks.slack.com/services/T07U456MZFB/.../jY1hgKafPxIckyLocZ0cZ9gj`
(lagrad i `~/.litellm-daily-spend-urls` på Coolify-servern)

## Meddelandeformat

```text
[Mage] Pipeline failure: games_pipeline
Pipeline games_pipeline failed at 2026-04-20T03:00:00. 
Logs: https://mage.theunnamedroads.com/pipelines/games_pipeline
```

## Testa att webhooken fungerar

```bash
ssh tha '
  SLACK_URL=$(grep "^SLACK_WEBHOOK_URL=" ~/.litellm-daily-spend-urls | cut -d= -f2-)
  curl -X POST -H "Content-Type: application/json" \
    -d "{\"text\":\"Test from Mage runbook\"}" \
    "$SLACK_URL"
'
```

## Trigga en test-notifikation via Mage

1. Öppna <https://mage.theunnamedroads.com/>
2. Öppna valfri pipeline (t.ex. `base_pipeline`)
3. Lägg till en block som failar (`raise Exception("test")`)
4. Kör pipeline → du får ett Slack-meddelande

Ta bort den test-block:en efteråt.

## Ändra vad som triggar notifikationer

Redigera `/home/src/mage_project/metadata.yaml` i containern och ändra
`alert_on`:

```yaml
notification_config:
  alert_on:
    - trigger_failure          # pipeline misslyckas
    - trigger_passed_sla       # pipeline tar för lång tid
    # - trigger_success        # aktivera för success-notiser (tyst kanal?)
```

Möjliga värden:
- `trigger_failure`
- `trigger_success`
- `trigger_passed_sla`

Efter ändring: `docker restart mage-k0oooc8ok4848880sk0g0kkc`.

## Lägg till Telegram (valfritt – custom callback)

Mage har inte inbyggt Telegram-stöd, men du kan skapa en **callback block**
i `mage_project/callbacks/` som skickar till Telegram vid pipeline-fel.

### Steg 1: Skapa `mage_project/callbacks/telegram_alert.py`

```python
import os
import requests

@callback('on_failure')
def notify_telegram(**kwargs):
    pipeline_uuid = kwargs.get('pipeline_uuid', 'unknown')
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '-1003767033253')
    if not token:
        return
    msg = (
        f"🚨 Mage pipeline failed: {pipeline_uuid}\n"
        f"https://mage.theunnamedroads.com/pipelines/{pipeline_uuid}"
    )
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=10,
    )
```

### Steg 2: Lägg till env vars i Coolify

```
TELEGRAM_BOT_TOKEN=8683132686:AAF5yJ206OcLKsSBx0n4Nm4uBAxcQlRbwyc
TELEGRAM_CHAT_ID=-1003767033253
```

### Steg 3: Referera callback från varje pipeline

Lägg till i `mage_project/pipelines/<pipeline>/metadata.yaml`:

```yaml
callbacks:
  - callback_name: telegram_alert
    callback_type: on_failure
```

### Steg 4: Testa

Kör en pipeline med en test-exception → både Slack och Telegram ska få
meddelanden.

## Övrigt

- **Opsgenie, Teams, Discord, Email:** Mage stödjer alla dessa. Se
  [Mage docs: Alerting](https://docs.mage.ai/observability/alerting/overview).
- **Retries:** Mage har inbyggd retry-policy per block. Konfigurera via
  `retry_config` i pipeline-metadata.
- **Silencing under underhåll:** Inaktivera trigger i UI:n istället för
  att stänga av notifikationer.
