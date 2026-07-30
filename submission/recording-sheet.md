# deadreckon — recording sheet

**To jest arkusz do czytania na żywo podczas nagrywania — prompter, nie
dokument analityczny.** Wersja z uzasadnieniami i rachunkiem czasu jest
w [`video-script.md`](video-script.md); ten plik ma tylko to, co
potrzebne w danej sekundzie: co jest na ekranie, co kliknąć, co
przeczytać na głos.

Czytaj każdy blok w tej samej kolejności: **CO WIDAĆ NA EKRANIE** →
**CO ROBIĘ** → **CO MÓWIĘ**. Kliknięcia i pauzy (⏸) rób zanim zaczniesz
czytać zdania z sekcji CO MÓWIĘ dla danego ujęcia — nie klikaj w
trakcie mówienia.

Łączny czas: **2:33**, twardy limit **3:00**.

---

## Przygotowanie przed nagraniem

1. Wyłącz powiadomienia na całym komputerze (Do Not Disturb / Focus).
2. Zamknij wszystkie zbędne aplikacje i karty przeglądarki. Zostaw
   tylko to, co potrzebne do nagrania.
3. Sprawdź, że DataHub stoi: `docker ps` pokazuje wszystkie kontenery
   jako `healthy`, a `http://localhost:9002` się otwiera.
4. Zaloguj się **raz** do DataHub UI (`datahub` / `datahub`) w
   przeglądarce, której użyjesz do nagrania. Nie musi to być karta,
   która zostanie widoczna w kadrze — liczy się tylko to, że sesja
   (cookie) jest aktywna. Tę kartę możesz potem zamknąć.
5. Otwórz **jedną czystą kartę** przeglądarki i wczytaj w niej
   `dashboard/index.html` (podwójne kliknięcie w Finderze albo
   przeciągnięcie pliku do okna przeglądarki). Potwierdź, że:
   - dashboard pokazuje **5 modeli** na zakładce **Matrix**,
   - dane są z wbudowanego `sample-run.json` — bez serwera, bez błędu,
   - w głównym widoku nie ma żadnego paska przewijania.
6. Ustaw okno przeglądarki na 1920×1080 (albo nagrywaj cały ekran w tej
   rozdzielczości).
7. Przygotuj osobno: slajd tytułowy (ujęcie 1) i slajd z diagramem
   architektury + numerami zgłoszeń OSS `#18657` / `#18675` (ujęcie 8) —
   gotowe do przełączenia jednym klawiszem/kliknięciem.
8. Zapamiętaj lokalizację pliku `examples/sample-run-edge-cases.json` —
   będzie potrzebny w oknie wyboru pliku w ujęciu 5.
9. Włącz nagrywanie ekranu i dźwięku. Odczekaj 2–3 sekundy ciszy na
   starcie (łatwiej się to przycina w montażu). Zacznij od ujęcia 1.

---

## Ujęcie 1 — Problem

**Czas ujęcia: 20s · Licznik: 0:00 → 0:20**

### CO WIDAĆ NA EKRANIE
Slajd tytułowy: napis "deadreckon" + jedna linia podtytułu. Żadnego
UI dashboardu jeszcze nie widać.

### CO ROBIĘ
Brak kliknięć. ⏸ Odczekaj ok. 1 sekundę w ciszy, potem czytaj.

### CO MÓWIĘ
> Production ML models rarely fail loudly.
> A serving metric looks fine. The pipeline runs on schedule.
> But four hops upstream, something breaks quietly.
> A column gets renamed. A table stops refreshing.
> Nobody connects the dots.
> deadreckon is an agent that walks a model's full lineage in DataHub.
> It uses metadata only.
> And it tells you not just what it found — it tells you what it could not check at all.

---

## Ujęcie 2 — Widok Matrix

**Czas ujęcia: 13s · Licznik: 0:20 → 0:33**

### CO WIDAĆ NA EKRANIE
Wciąż slajd tytułowy z ujęcia 1.

### CO ROBIĘ
1. Przełącz się na kartę przeglądarki z otwartym dashboardem
   (przygotowaną wcześniej — zakładka **Matrix** jest już aktywna).
2. Najedź kursorem na wiersz **taxi_fare_predictor_v1** (ostatni,
   najniższy wiersz tabeli) i przytrzymaj kursor chwilę.

### CO MÓWIĘ
> Five models. Three detectors each.
> Every cell has one of three states.
> Pass. Finding. Or insufficient data.
> Never just red or green.
> And here is the control model: taxi_fare_predictor_v1.
> Checked clean, across the board.

---

## Ujęcie 3 — Drill-down: uzasadnienie INSUFFICIENT_DATA

**Czas ujęcia: 17s · Licznik: 0:33 → 0:50**

### CO WIDAĆ NA EKRANIE
Widok Matrix, ten sam co w ujęciu 2. Kursor wciąż przy dolnym wierszu.

### CO ROBIĘ
1. Przesuń kursor do góry, do pierwszego wiersza tabeli —
   **customer_churn_predictor_v2**.
2. Kliknij komórkę w kolumnie **D1 Frozen training source** —
   pomarańczowy przycisk **"? INSUFFICIENT DATA"**.
3. ⏸ Poczekaj ok. 1 sekundę, aż okno drill-down w pełni się otworzy.

### CO MÓWIĘ
> You can click any cell. Even this one.
> D1 did not pass this model.
> It did not flag it either.
> It is telling us the metadata it needed is simply not there.
> That is a different claim than "safe".
> Most systems do not make this distinction.

---

## Ujęcie 4 — Ranking & Coverage, czysty przebieg

**Czas ujęcia: 11s · Licznik: 0:50 → 1:01**

### CO WIDAĆ NA EKRANIE
Otwarte okno drill-down z ujęcia 3, z uzasadnieniem D1
INSUFFICIENT DATA.

### CO ROBIĘ
1. Kliknij przycisk **"✕"** w prawym górnym rogu okna, żeby je zamknąć.
2. Kliknij zakładkę **"Ranking & Coverage"** (prawy górny róg strony,
   obok zakładki "Matrix").
3. ⏸ Poczekaj ok. 1 sekundę, aż wykres się w pełni wyrenderuje.
4. Wskaż kursorem pusty, zacieniony pas na dole wykresu — napis
   **"UNVERIFIED — NOT THE SAME AS SAFE"**.

### CO MÓWIĘ
> Risk and coverage are plotted as two separate axes.
> Right now, the unverified zone down here is empty.
> It exists by design. Not for one demo case.

---

## Ujęcie 5 — Podmiana pliku: strefa zapełnia się na żywo [NOTES.md]

**Czas ujęcia: 12s · Licznik: 1:01 → 1:13**

### CO WIDAĆ NA EKRANIE
Wykres Ranking & Coverage z ujęcia 4, dane wciąż z `sample-run.json`,
pusta strefa "unverified" widoczna na dole.

### CO ROBIĘ
1. Kliknij przycisk **"📁 Load run JSON"** (prawy górny róg strony).
2. W oknie systemowym wybierz plik
   `examples/sample-run-edge-cases.json` i potwierdź (Open / Otwórz).
3. ⏸ Poczekaj ok. 1 sekundę, aż wykres się przeładuje.
4. Wskaż kursorem punkt, który pojawił się **wewnątrz** zacienionej
   strefy (model `session_ltv_predictor_v2`).

### CO MÓWIĘ
> Now watch a different run load.
> There.
> This model scored zero. But it was not checked at all.
> It lands exactly where it should.
> Right next to another zero-score model that is actually clean.

---

## Ujęcie 6 — Podgraf zapłonu

**Czas ujęcia: 20s · Licznik: 1:13 → 1:33**

### CO WIDAĆ NA EKRANIE
Wykres Ranking & Coverage na danych z `sample-run-edge-cases.json`
(3 modele), punkt w strefie "unverified" wciąż widoczny.

### CO ROBIĘ
1. Odśwież kartę przeglądarki (**Cmd+R** / **F5**). To przywraca
   domyślny, wbudowany przebieg `sample-run.json` — nie trzeba
   wczytywać pliku ręcznie ponownie.
2. ⏸ Poczekaj ok. 2 sekundy, aż strona się w pełni przeładuje i pokaże
   domyślny widok **Matrix** (5 modeli).
3. Kliknij komórkę w wierszu **customer_churn_predictor_v2**, kolumna
   **D2 Schema drift under a feature** — czerwony przycisk
   **"✕ FINDING"**.
4. ⏸ Poczekaj, aż okno drill-down się otworzy, i przewiń w dół do
   sekcji z podgrafem — pasek węzłów połączonych strzałkami, poniżej
   opisu znaleziska.

### CO MÓWIĘ
> Back to the real run.
> Same model. Its schema-drift finding.
> Here is the ignition path.
> The exact node where this started, annotated with why.
> Plus a real deep link into DataHub.
> This is not a redraw of DataHub's own lineage view.
> It is just the one thing that view does not say.

---

## Ujęcie 7 — Wejście do DataHuba: zapis do grafu na żywo [NOTES.md]

**Czas ujęcia: 22s · Licznik: 1:33 → 1:55**

### CO WIDAĆ NA EKRANIE
Otwarte okno drill-down z ujęcia 6, widoczny podgraf zapłonu i link
**"Open full lineage in DataHub →"** pod nim.

### CO ROBIĘ
1. Kliknij link **"Open full lineage in DataHub →"**. Otworzy się
   **nowa karta** przeglądarki z profilem modelu
   `customer_churn_predictor_v2` w DataHub (przeglądarka musi być
   wcześniej zalogowana — patrz "Przygotowanie przed nagraniem", punkt 4).
2. Przełącz się na tę nową kartę.
3. ⏸ Poczekaj ok. 1–2 sekundy, aż strona się w pełni załaduje.
4. Wskaż kursorem tag **"undertow:at-risk"** w prawym panelu, sekcja
   **"Tags"**.
5. Kliknij zakładkę **"Documentation"** (górny pasek zakładek, obok
   "Summary").
6. Wskaż kursorem trzy wpisy zaczynające się od **"[deadreckon]"** w
   sekcji **"Resources"**, zwłaszcza trzeci: **"[deadreckon] - not
   checked: ..."**.

### CO MÓWIĘ
> And that link is real.
> Same model. Live in DataHub.
> Tagged undertow at-risk.
> And three deadreckon notes, right in its Documentation tab.
> Including one that says exactly what was not checked.
> This is not a report sitting in a file.
> It is written back into the graph.

---

## Ujęcie 8 — Architektura i kontrybucje OSS

**Czas ujęcia: 30s · Licznik: 1:55 → 2:25**

### CO WIDAĆ NA EKRANIE
Strona modelu w DataHub UI, zakładka Documentation, z ujęcia 7.

### CO ROBIĘ
1. Przełącz się na przygotowany wcześniej slajd z diagramem
   architektury (np. zrzut sekcji "Architecture" z README, albo
   wyrenderowany diagram Mermaid).
2. ⏸ Zostań na tym slajdzie ok. 2–3 sekundy.
3. Przełącz się na slajd/tekst z numerami dwóch zgłoszeń: **#18657** i
   **#18675**.

### CO MÓWIĘ
> Under the hood: three detectors read DataHub's ML lineage.
> They go through DataHub's own MCP server.
> They score by weight and blast radius.
> And they write everything straight back into the graph you just saw.
> The full architecture diagram is in the README.
> Building this also found two real DataHub bugs.
> Both are filed upstream, and fixed in this repo.
> One was an OpenSearch crash. The other, a broken Document-entity link.

---

## Ujęcie 9 — Zakończenie

**Czas ujęcia: 8s · Licznik: 2:25 → 2:33**

### CO WIDAĆ NA EKRANIE
Slajd z numerami zgłoszeń OSS z ujęcia 8.

### CO ROBIĘ
1. Przełącz się na końcowy slajd: adres repozytorium
   (`github.com/AnubisCrypto666/deadreckon`) + licencja Apache 2.0.

### CO MÓWIĘ
> Code, examples, and full setup instructions are all in the repo below.
> Apache 2.0 licensed.

---

## Po nagraniu — lista kontrolna

1. Zatrzymaj nagrywanie. Poczekaj, aż plik się w pełni zapisze.
2. Odtwórz całość od razu — sprawdź, czy dźwięk w ogóle się nagrał.
3. Sprawdź łączny czas — musi być poniżej **3:00**.
4. Sprawdź, czy fragment w DataHub (ujęcie 7) jest czytelny: tag i
   trzy notatki `[deadreckon]` widoczne bez przycinania.
5. Zapisz surowy plik w dwóch miejscach (kopia zapasowa), zanim
   zaczniesz montaż.
6. Jeśli coś się nie udało, zanotuj dokładny znacznik czasu — nagraj
   ponownie tylko ten fragment, nie całość.
7. Po eksporcie: wrzuć na YouTube/Vimeo jako **publiczne**, skopiuj
   link.
8. Wklej link do formularza Devpost.
