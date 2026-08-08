# Oracle-Server: leads-api mit HTTPS

Domain (kostenlos via nip.io, zeigt automatisch auf 130.61.64.191):

    130-61-64-191.nip.io

## 1. Oracle Cloud Security List / Firewall

Im OCI-Dashboard bei der Instanz -> zugehöriges Subnet -> Security List:
Ingress Rules hinzufügen für Port 80 und 443 (Quelle 0.0.0.0/0, TCP).

Auf dem Server selbst (falls iptables/ufw aktiv ist):

    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp

Port 8000 NICHT nach außen freigeben - der ist nur noch für nginx
(localhost) gedacht, das Backend soll nur über 443 erreichbar sein.

## 2. nginx + certbot installieren

    sudo apt update
    sudo apt install -y nginx certbot python3-certbot-nginx

    sudo cp deploy/nginx-leads-api.conf /etc/nginx/sites-available/leads-api
    sudo ln -s /etc/nginx/sites-available/leads-api /etc/nginx/sites-enabled/
    sudo nginx -t
    sudo systemctl reload nginx

## 3. Zertifikat holen (certbot patcht die nginx-Config automatisch für HTTPS + Redirect)

    sudo certbot --nginx -d 130-61-64-191.nip.io

Fragt nach einer E-Mail (für Ablauf-Erinnerungen) und akzeptiert danach
automatisch AGB. certbot fügt selbst listen 443 ssl; und die
Zertifikatspfade in die Config ein und richtet einen Cronjob/systemd-Timer
für die automatische Erneuerung ein (Zertifikate gelten 90 Tage).

Test der Auto-Renewal:

    sudo certbot renew --dry-run

## 4. Danach prüfen

    curl https://130-61-64-191.nip.io/health
    # -> {"status":"ok"}

## 5. .env auf dem Server anpassen

    ALLOWED_ORIGINS="https://<dein-vercel-projekt>.vercel.app"

(erst final setzen, sobald die Vercel-URL feststeht - bis dahin reicht
auch "*" zum Testen)

## 6. Auf Vercel als BACKEND_URL eintragen

    BACKEND_URL=https://130-61-64-191.nip.io
    BACKEND_API_KEY=<Wert aus .env / API_KEY>
