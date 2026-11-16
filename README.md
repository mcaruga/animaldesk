# AnimalDesk 🐕 — golden retriever da desktop

Un cucciolo di golden retriever che vive **sopra** le tue finestre, piccolo, sempre
visibile e sempre impegnato a fare qualcosa. Codice e grafica **100% originali**:
il cane è disegnato a runtime con `QPainter` (vettoriale), quindi non ci sono
sprite, GIF o asset di terze parti da trascinarsi dietro.

![pose](assets/icon-128.png)

## Tre aspetti, stesso cervello

| Aspetto | Come | Dove |
|---|---|---|
| **Foto reale** (default) | la foto vera dell'animale, ritagliata a livello del singolo pelo e animata con un **rig a mesh**: la testa gira con parallasse (il naso si sposta piu' del cranio), si inclina attorno al collo, le orecchie seguono con una molla, le palpebre sono pelo vero che scende sull'occhio | `skin.py`, `assets/skins/<nome>/` |
| **Disegno: golden retriever** | vettoriale con gradienti, pelo e occhio con iride | `dogart.py` |
| **Disegno: barboncino** | stesso scheletro, manto riccio, ciuffo e coda a pompon | `breeds.py` |

Con la foto il cane sta **affacciato dal bordo basso dello schermo**: di una foto
a mezzo busto esistono solo testa e petto, quindi il taglio resta nascosto sotto
il bordo invece di fluttuare a mezz'aria.

### Azioni della pelle fotografica

Seduto, dormi, **scrivi alla tastiera**, **nascondino**, lecca la zampa, guardati
intorno, **testa di lato**, grattata, occhi felici, linguetta, dispetto, abbaia.
Lo sguardo segue il puntatore quando e' vicino. Gli spostamenti del viso sono
limitati di proposito (un test verifica che nessun vertice si muova piu' del 9%
della taglia): il muso non si deforma mai.

### Costumi

Cappello di Babbo Natale, occhiali da sole + salvagente, maschera e berretto da
sci con gli sci. Seguono la testa quando gira o si inclina. Menu **Costume**:
*Automatico* sceglie per data (1 dic - 6 gen Natale, 15 giu - 7 set mare), oppure
si forza quello che si vuole.

### Il tuo animale, in automatico

Menu **Aspetto -> Nuovo animale da foto...** oppure:

```bash
pip install -e ".[foto]"
export ANTHROPIC_API_KEY=...        # facoltativa, vedi sotto
python -m animaldesk.tools.auto_skin foto.jpg --nome fido
```

1. un modello di visione (Claude) guarda la foto e restituisce, come JSON
   validato da schema, il riquadro testa+petto e i punti del viso;
2. lo sfondo viene tolto (GrabCut guidato da quei punti + alpha matting);
3. i punti vengono rifiniti sui pixel (centro reale di occhi e naso);
4. si scrivono `sprite.png` e `rig.json`.

Tutte le azioni e i costumi sono guidati dal rig, quindi funzionano subito sul
nuovo animale: non c'e' niente da ridisegnare. Se il modello giudica la foto
inadatta (muso girato, occhio coperto, testa tagliata) lo dice invece di
produrre una pelle sbagliata.

Senza chiave API si usa una stima dai pixel (le tre macchie scure del muso):
funziona su animali chiari con occhi e naso ben visibili, e in ogni caso la
finestra mostra i punti e li lascia trascinare al posto giusto.

Foto che rendono meglio: muso di fronte o di tre quarti, occhi entrambi
visibili, bocca chiusa, sfondo che stacca dal pelo.

## Cosa fa il cane

| Comportamento | Cosa vedi |
|---|---|
| `idle` | respira, sbatte le palpebre, scodinzola |
| `walk` / `run` | cammina e corre sul bordo inferiore dello schermo, lingua fuori quando corre |
| `sit` | si siede |
| `sleep` | si sdraia e fa `z z z` (recupera energia) |
| `bark` | abbaia con fumetto ("Woof!", "Bau!") |
| `dig` | scava e lancia terra |
| `scratch` | si gratta l'orecchio |
| `spin` | si rincorre la coda |
| `roll` | capriola completa |
| `jump` | salto con gravità reale |
| `chase` | insegue il puntatore del mouse |
| `fetch` | rincorre la palla, la prende in bocca e te la riporta |
| `eat` | va alla ciotola e mangia (riduce la fame) |
| `dragged` / `fall` | lo prendi in mano, zampe che si agitano, poi cade e atterra |
| `pet` | coccola: occhi socchiusi, guance rosse, cuoricini |

Il cane ha tre statistiche (**energia**, **fame**, **felicità**) che cambiano nel
tempo e pesano sulla scelta del prossimo comportamento: stanco → dorme, affamato
→ va alla ciotola, felice → fa più capriole. Le statistiche vengono salvate e
ritrovate al riavvio.

## Come si usa

| Gesto | Effetto |
|---|---|
| Trascinamento col tasto sinistro | lo prendi in braccio, al rilascio cade |
| Doppio click | carezza (cuoricini) |
| Tasto destro | menu completo |
| Rotellina sopra il cane | cambia la taglia |
| Icona nella tray | stesso menu + statistiche |

Dal menu: comandi diretti (siediti, dormi, abbaia, scava, capriola, rincorri la
coda, salta, grattati), **lancia la palla**, **dai da mangiare**, *insegui il
mouse*, taglia (mini/piccolo/medio/grande), vivacità, scelta dello schermo su
setup multi-monitor, **avvio automatico al login**, esci.

## Avvio

```bash
pip install PySide6-Essentials
python -m animaldesk
```

Su Linux serve un desktop con supporto alle finestre trasparenti e alla tray
(X11 o Wayland con XWayland).

## Build eseguibile

```bash
pip install -e ".[build]"
python packaging/make_icon.py          # rigenera le icone dal vettoriale
pyinstaller packaging/animaldesk.spec     # -> dist/AnimalDesk(.exe) / AnimalDesk.app
```

Su macOS il bundle è marcato `LSUIElement`, quindi niente icona nel Dock: solo
la tray e il cane.

## Com'è fatto

```
animaldesk/
├── skin.py      pelle fotografica: rig a mesh sulla foto vera
├── dogart.py    disegno vettoriale realistico, parametrico per razza
├── breeds.py    razze (golden, barboncino)
├── render.py    palla, ciotola, particelle, fumetti, icona
├── outfits.py   costumi stagionali e oggetti di scena (tastiera, salvagente, sci)
├── tools/auto_skin.py  da foto a pelle in automatico (visione AI + ritaglio + rig)
├── pet.py       macchina a stati + fisica + statistiche (nessuna dipendenza Qt)
├── props.py     palla, ciotola, sistema di particelle (nessuna dipendenza Qt)
├── overlay.py   finestra trasparente a tutto schermo, maschera click-through
├── app.py       tray, menu, impostazioni
├── config.py    configurazione JSON nella cartella utente
└── autostart.py avvio al login su Windows / macOS / Linux
```

La finestra è un overlay a tutto schermo, frameless, `WindowStaysOnTopHint` e
`WA_TranslucentBackground`. Ad ogni frame viene ricalcolata una **maschera**
(`setMask`) che copre solo cane, palla, ciotola, fumetto e particelle: tutto il
resto dello schermo resta cliccabile normalmente, quindi l'overlay non ruba mai
i click al desktop.

`pet.py` e `props.py` non importano Qt: sono matematica pura e si testano senza
display.

```bash
python -m pytest -q      # 68 test
```

## Licenza

MIT. Grafica e logica scritte da zero per questo progetto.
