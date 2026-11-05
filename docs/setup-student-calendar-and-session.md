# Ekstra elevkalender og genbrug af login

## Kalender for elev 67380948067

Workflowet bygger nu en separat fil med samme periode, parser, filtrering,
lektier, lokaler og håndtering af aflyste timer som den oprindelige kalender:

`https://2zap2.github.io/Lectio/calendar-67380948067.ics`

Linket bliver tilgængeligt, når koden er sendt til GitHub, workflowet har kørt
med et gyldigt login, og GitHub Pages har publiceret filen. Det er ikke en
forudfyldt eller tom kalender; første fil dannes ud fra det rigtige elevskema.

Den oprindelige kalender beholder sit filnavn og sine elever. Opgaver og ledige
lokaler hentes fortsat kun for den oprindelige konfiguration. Ekstra elevkalendere
kan tilføjes ved at gentage `--additional-student-id` i workflowet.

Lokal kørsel med eksisterende miljøvariabler:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -m lectio_sync --fetch --out docs/calendar.ics --additional-student-id 67380948067
```

## Hvad der er rettet i login

Den gamle HTTP-kode genbrugte en fast Cookie-header uden at behandle
`Set-Cookie`. Den nye kode deler en cookie jar mellem alle forespørgsler og
behandler både fornyelse, omdirigeringer og sletning. Importerede cookies erstattes
af serverens korrekt afgrænsede version, så en gammel værdi ikke sendes sammen
med en ny værdi med samme navn.

Browserprofilen genbruges stadig, men sessionscookies gemmes nu også eksplicit
mellem kørsler. Det omfatter sessionscookies fra loginudbyderen, så dens eksisterende
login kan bruges igen. Hvis skemaet viser en udløbet session, åbner programmet først Lectios normale
`login.aspx` i den gemte profil. Her kan loginudbyderens gemte SSO-login ofte
gennemføre genlogin uden manuel indtastning. Cookies til loginudbyderen bliver på computeren; kun cookies,
der matcher Lectios værtsnavn og sti, eksporteres til GitHub. Udløbstider ændres ikke.

Lectios JavaScript i repoets gemte side viser `SessionHelper` og et kald til
`/lectio/<skole>/ping.aspx` ved "Forlæng session". Det dokumenterer en
sessionsforlængelse. Den aktuelle side blev også kontrolleret i Chrome: den
initialiserede sessionshjælperen med advarsel efter 3000 sekunder og timeout efter
3540 sekunder (59 minutter). Det er forskelligt fra loginudbyderens længere
SSO-session og er ikke en garanti for en måneds login. Kalenderens normale sidehentninger giver også serveren mulighed
for at forny cookies. Den faktiske loginperiode skal afprøves mod Lectio over tid.

Et offentligt skema er ikke længere nok til at erklære login vellykket:
refresheren kræver også Lectios markering af login eller et "Log ud"-element.

## Aktivering på Windows

Brug den mappe, hvor den opdaterede kode er installeret. Eksisterende Python,
Playwright, Chromium og GitHub CLI kan genbruges. Kontrollér GitHub-login med
`gh auth status`, hvis en opdatering af secret fejler.

1. Kør `.\scripts\refresh_cookie.ps1 -Repo 2zap2/Lectio`. Gennemfør login,
   hvis Lectio beder om det. Den dedikerede profil har sit eget login; den
   overtager ikke automatisk login fra din almindelige Chrome-profil.
2. Kør `.\scripts\register_scheduled_task.ps1` igen for at opdatere opgaven.
   Den kører ved Windows-login, efter dvale og hver halve time. Den første
   periodiske kørsel starter efter cirka ét minut.
3. Start workflowet med `gh workflow run update-calendar.yml --repo 2zap2/Lectio`.
4. Tilføj kalenderlinket ovenfor som abonnement i kalenderappen efter en
   vellykket opdatering og publicering.

Baggrundskørsler åbner ingen loginvinduer. Exitkode 2 i
`%LOCALAPPDATA%\lectio-sync\auto-refresh.log` betyder, at trin 1 skal gentages.
Netværksfejl betyder ikke nødvendigvis, at login er udløbet.

Computeren skal være tændt og have netværk, for at Windows-opgaven kan forny og
sende cookies. Profil og sessionscookies ligger uden for repoet i
`%LOCALAPPDATA%\lectio-sync\playwright-profile`. De skal behandles som loginoplysninger.

## Valgfrit: Gem fornyede cookies direkte fra GitHub Actions

For at bevare serverens fornyelser mellem workflowkørsler kan du oprette
repository-secret `LECTIO_SECRETS_TOKEN` med et fine-grained GitHub-token,
begrænset til dette repository og repository-rettigheden **Secrets: Read and write**.
Det almindelige `GITHUB_TOKEN` kan ikke opdatere Actions-secrets.

```powershell
gh secret set LECTIO_SECRETS_TOKEN --repo 2zap2/Lectio
```

Kommandoen beder om tokenet. Workflowet bruger det til at opdatere
`LECTIO_COOKIE_HEADER`, hvis serveren ændrer cookies. Værdier sendes via stdin
og skrives ikke i loggen, heller ikke ved fejl. En fornyelse gemmes også, hvis
en efterfølgende hentning eller parsing fejler.

Uden dette valg fungerer workflowet med den seneste cookie fra Windows-opgaven.
Valget kan reducere afhængigheden af computeren, men erstatter ikke et nyt
browserlogin, når Lectio eller SSO faktisk kræver det. Ingen løsning her
automatiserer MitID eller kan forlænge en session, som serveren har afsluttet.

## Hvilke lokale kopier der blev fundet

| Mappe under `.1Kodeprojekter` | Fund |
|---|---|
| `Lectio` | Kalenderprojektet med GitHub-origin `2zap2/Lectio`. Lokal `main` var fra 27. marts 2026; den senest hentede `origin/main` fra 2. august 2026. Kildekoden i de to commits var ens; forskellene var kalenderdata. Der var også lokale kodeændringer. |
| `Lectio - Kopi` | Ekstra kopi; blev ikke brugt som implementeringsgrundlag. |
| `Lectio-calendar-publisher-extension` | Separat browserudvidelse med publisher-backend. Den kræver særskilt opsætning og er ikke en erstatning for GitHub Pages-workflowet. |

Ændringerne her er lavet i arbejdsmappen for denne samtale. De oprindelige
projektmapper er ikke overskrevet. Netværksadgang til GitHub og Lectio var
ikke tilgængelig fra Git/Python-miljøet. Browseren viste dog den aktuelle
GitHub-version (seneste commit `dbce567`, 1. november 2026) med samme seneste
kildekodecommit fra marts, og elevens rigtige skema blev åbnet med det eksisterende
browserlogin. Download af GitHub-arkivet blev blokeret af browseren. Den nye
refresher og publicering er ikke verificeret mod live-tjenesterne.
