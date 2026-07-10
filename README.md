# SHAPPNO PREMIUM VPS

## Features
- ✅ Multi-server management
- ✅ Auto-restart with custom intervals
- ✅ File manager (upload/download/edit)
- ✅ Package manager (pip/npm/apt/pkg)
- ✅ Telegram bot hosting
- ✅ 10+ themes with matrix animation
- ✅ Dual password system (Secret + User)

## Default Passwords
- Secret: `shappno` (Can change user password)
- User: `shappno` (Cannot change password)

## Deploy on Render
1. Fork this repository
2. Create a new Web Service on Render
3. Set `SELF_URL` environment variable to your Render URL
4. Deploy!

## Environment Variables
- `SELF_URL`: Your Render app URL (for self-ping)
- `PORT`: (optional, default 8080)
- `DEBUG`: (optional, default False)

## Tech Stack
- Flask 3.0.0
- psutil for system stats
- pyTelegramBotAPI for Telegram bots
- TailwindCSS for UI