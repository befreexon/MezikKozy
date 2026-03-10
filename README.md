# Mezi Kostkami

Kasinová hra štěstí a odvahy pro 2–4 hráče, implementovaná jako Django webová aplikace s real-time multiplayerem přes WebSocket.

## Obsah

- [Lokální vývoj](#lokální-vývoj)
- [Nasazení na Kubernetes cluster](#nasazení-na-kubernetes-cluster)
  - [Příprava: build a push image](#1-build-a-push-docker-image)
  - [Příprava: secret s přihlašovacími údaji](#2-vytvoření-secretu)
  - [Helm deploy](#3-nasazení-helm-chartem)
  - [Aktualizace aplikace](#aktualizace-aplikace)
- [CI/CD přes GitHub Actions](#cicd-přes-github-actions)

---

## Lokální vývoj

Aplikace běží v Dockeru pomocí Docker Compose. Součástí stacku jsou kontejnery `web` (Django/Daphne), `db` (PostgreSQL) a `redis`.

### Požadavky

- Docker a Docker Compose

### Spuštění

```bash
# 1. Zkopírovat a případně upravit konfiguraci
cp .env.example .env

# 2. Sestavit image a spustit stack
docker compose up --build
```

Aplikace je dostupná na **http://localhost:8000**.

Při prvním spuštění `entrypoint.sh` automaticky:
1. počká na připravenost PostgreSQL,
2. spustí databázové migrace (`manage.py migrate`),
3. nastartuje Daphne ASGI server.

### Zastavení a čištění

```bash
# Zastavit kontejnery (zachovat databázi)
docker compose down

# Zastavit a smazat i databázový volume
docker compose down -v
```

---

## Nasazení na Kubernetes cluster

Aplikace se nasazuje pomocí vlastního Helm chartu `django` (viz `infrastructure/charts/django/`). Chart je generický a lze ho použít pro libovolný Django projekt.

Předpoklady:
- `kubectl` nakonfigurovaný na cluster `cmn-test`
- `helm` ≥ 3.x
- přihlášení k Harbor registry (`harbor.servisovadlo.eu`)

### 1. Build a push Docker image

#### Lokálně (bez CI/CD)

```bash
# Přihlásit se do Harbor (pokud ještě nejste)
docker login harbor.servisovadlo.eu

# Sestavit image a označit ho
docker build -t harbor.servisovadlo.eu/apps/mezikkozy:latest .

# Volitelně označit konkrétní verzí (doporučeno)
docker tag harbor.servisovadlo.eu/apps/mezikkozy:latest \
           harbor.servisovadlo.eu/apps/mezikkozy:$(git rev-parse --short HEAD)

# Pushnout do registry
docker push harbor.servisovadlo.eu/apps/mezikkozy:latest
docker push harbor.servisovadlo.eu/apps/mezikkozy:$(git rev-parse --short HEAD)
```

> **Tip:** Tag `latest` je vhodný pro testovací prostředí. Pro produkci použijte konkrétní tag (git SHA nebo verzi) a upravte `django.image.tag` v `helm-mezikkozy.yaml`. Díky `pullPolicy: Always` cluster vždy stáhne aktuální verzi obrazu s daným tagem.

### 2. Vytvoření Secretu

Secret obsahuje citlivé hodnoty, které **nejsou součástí repozitáře**. Vytvořte ho ručně jednou před prvním nasazením:

```bash
kubectl create secret generic mezikkozy-secret \
  --from-literal=secret-key='<silný-django-secret-key>' \
  --from-literal=db-password='<silné-heslo-pro-postgresql>' \
  -n default
```

Jako `secret-key` použijte náhodný řetězec, například:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

> Secret je označen anotací `helm.sh/resource-policy: keep`, takže ho `helm uninstall` nesmaže.

### 3. Nasazení Helm chartem

```bash
cd infrastructure

helm upgrade --install mezikkozy charts/django \
  -n default \
  -f clusters/cmn-test/default/helm-mezikkozy.yaml
```

Při nasazení Helm chart automaticky:
1. vytvoří PostgreSQL StatefulSet, Redis Deployment a Django Deployment,
2. init kontejner `wait-for-db` počká na dostupnost databáze,
3. init kontejner `django-migrate` spustí databázové migrace,
4. nastartuje hlavní aplikační kontejner s Daphne,
5. vytvoří Ingress s TLS certifikátem od Let's Encrypt.

Stav nasazení ověříte:
```bash
kubectl get pods -n default
kubectl get ingress -n default
kubectl logs -n default deploy/mezikkozy -f
```

Certifikát Let's Encrypt se vystaví automaticky — první spuštění může trvat minutu.

### Aktualizace aplikace

Po každém buildu a pushnutí nového image stačí:

```bash
# Restartovat Deployment (stáhne nový :latest image)
kubectl rollout restart deployment/mezikkozy -n default

# Nebo nasadit s konkrétním tagem
# 1. Upravit tag v helm-mezikkozy.yaml, nebo předat přes --set:
helm upgrade mezikkozy charts/django \
  -n default \
  -f clusters/cmn-test/default/helm-mezikkozy.yaml \
  --set django.image.tag=$(git rev-parse --short HEAD)
```

### Odinstalování

```bash
helm uninstall mezikkozy -n default

# Secret a PersistentVolumeClaim jsou chráněny — smažte ručně pokud chcete čistý stav:
kubectl delete secret mezikkozy-secret -n default
kubectl delete pvc -l app.kubernetes.io/instance=mezikkozy -n default
```

---

## CI/CD přes GitHub Actions

Workflow `.github/workflows/build.yaml` automaticky sestaví a pushne image do Harbor při každém push na větev `main`.

### Nastavení

V nastavení GitHub repozitáře (**Settings → Secrets and variables → Actions**) přidejte:

| Secret | Hodnota |
|--------|---------|
| `HARBOR_USERNAME` | Uživatelské jméno do Harbor |
| `HARBOR_PASSWORD` | Heslo nebo Robot Account token |

Workflow vytvoří dva tagy:
- `harbor.servisovadlo.eu/apps/mezikkozy:latest` — vždy ukazuje na poslední verzi z `main`
- `harbor.servisovadlo.eu/apps/mezikkozy:sha-<zkrácené-SHA>` — pro traceabilitu konkrétního commitu

Po úspěšném buildu spusťte aktualizaci dle postupu výše.
