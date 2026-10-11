# MailPilot backend structure

Mobile app was split out. It now lives next to this repo:

```
Desktop/office/
├── MailPilot/              # this Django project
│   ├── manage.py
│   ├── mailpilot/
│   ├── core/
│   ├── api/v1/             # JWT API for mobile + clients
│   ├── templates/ + static/
│   └── docs/API_REFERENCE.md
└── mailPilotMobile/        # Expo app (separate folder)
```

## Boundaries

| Project | Owns |
|---------|------|
| `MailPilot` | Database, business rules, `/api/v1`, web UI |
| `mailPilotMobile` | Screens, JWT client, Expo Go / store builds |

Communication: **HTTP + JWT** only. For phones use:

```bat
python manage.py runserver 0.0.0.0:8000
```
