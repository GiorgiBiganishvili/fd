"""Beam/Viterbi phrase optimization, simultaneous string allocation and evidence."""
from __future__ import annotations

from dataclasses import dataclass

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import Evidence, NoteEvent, Position
from guitar_tab_ai.core.timeline import TemporalIndex
from guitar_tab_ai.guitar.model import GuitarModel


@dataclass
class State:
    cost: float
    occupied: dict[int, tuple[float, int]]
    last: Position | None
    parent: State | None
    chosen: Position | None


class FingeringSolver:
    """Optimize an entire sequence, retaining sustained string occupancy.

    Beam pruning bounds polyphonic search. An impossible note is kept unassigned
    and flagged instead of silently creating an unplayable chord.
    """
    def __init__(self, guitar: GuitarModel, config: AppConfig):
        self.guitar, self.config = guitar, config

    def solve(self, notes: list[NoteEvent], evidence: list[Evidence] | None = None) -> list[NoteEvent]:
        evidence = evidence or []
        ordered = sorted((n.model_copy(deep=True) for n in notes), key=lambda n: (n.start, n.midi))
        index = TemporalIndex(evidence, lambda e: e.time)
        beam = [State(0, {}, None, None, None)]
        for note in ordered:
            nearby = index.around(note.start)
            candidates = self.guitar.candidates(note.midi)
            if note.manual_override and note.string is not None:
                candidates = [Position(string=note.string, fret=note.fret)]
            next_beam: list[State] = []
            for state in beam:
                occupied = {s: (end, fret) for s, (end, fret) in state.occupied.items()
                            if end > note.start + 0.025}
                for position in candidates:
                    if position.string in occupied:
                        continue
                    cost = self.position_cost(position, note, nearby)
                    if state.last:
                        cost += self.transition_cost(state.last, position)
                    positive_frets = [f for _, f in occupied.values() if f > 0]
                    if position.fret > 0:
                        positive_frets.append(position.fret)
                    if positive_frets:
                        span = max(positive_frets) - min(positive_frets)
                        cost += max(0, span-4)**2 * self.config.weights.stretch
                    next_beam.append(State(state.cost + cost,
                                           {**occupied, position.string: (note.end, position.fret)},
                                           position, state, position))
                if not candidates or all(p.string in occupied for p in candidates):
                    next_beam.append(State(state.cost+12, occupied, state.last, state, None))
            unique = {}
            for state in next_beam:
                key = (state.last.string if state.last else 0, state.last.fret if state.last else 0,
                       tuple(sorted(state.occupied.items())))
                if key not in unique or state.cost < unique[key].cost:
                    unique[key] = state
            beam = sorted(unique.values(), key=lambda s: s.cost)[:self.config.beam_width]
        if not beam:
            return ordered
        best = beam[0]
        choices = []
        while best.parent is not None:
            choices.append(best.chosen)
            best = best.parent
        choices.reverse()
        for note, position in zip(ordered, choices):
            note.alternatives = self.guitar.candidates(note.midi)
            if position:
                # Assign via revalidation to keep string/fret invariant atomic.
                values = note.model_dump()
                values.update(string=position.string, fret=position.fret)
                replacement = NoteEvent.model_validate(values)
                note.__dict__.update(replacement.__dict__)
                ambiguity = len(note.alternatives)
                matching = [e for e in index.around(note.start) if e.synchronized
                            and e.position == position]
                confidence = max((e.confidence for e in matching), default=0)
                note.confidence.fingering = min(0.9, (0.75 if ambiguity == 1 else 0.45) + 0.4*confidence)
            else:
                note.confidence.fingering = 0
            note.confidence.final = min(note.confidence.audio or max(note.confidence.video,
                                                                   note.confidence.ocr),
                                        note.confidence.fingering)
            note.uncertain = note.confidence.final < self.config.confidence_threshold
            if note.manual_override:
                note.uncertain = False
        return ordered

    def transition_cost(self, before: Position, after: Position) -> float:
        w = self.config.weights
        # Open strings do not require the hand to jump to the nut.
        shift = abs(before.fret-after.fret) if before.fret and after.fret else 0
        return shift*w.fret_distance + abs(before.string-after.string)*w.string_distance

    def position_cost(self, position: Position, note: NoteEvent, evidence: list[Evidence]) -> float:
        w = self.config.weights
        cost = 0.008 * position.fret - (w.open_string if position.fret == 0 else 0)
        for e in evidence:
            if not e.synchronized or abs(e.time-note.start) > 0.15:
                continue
            if e.hand_center_fret is not None and position.fret:
                cost += abs(position.fret-e.hand_center_fret)*w.hand_position*e.confidence
            if self.guitar.midi_at(e.position) != note.midi:
                continue  # Other chord tones are not evidence against this note.
            weight = w.ocr if e.source == "ocr" else w.video
            distance = min(6, abs(position.fret-e.position.fret) + 2*abs(position.string-e.position.string))
            cost += weight * e.confidence * distance
        return cost


class PlayabilityValidator:
    def validate(self, notes: list[NoteEvent]) -> list[str]:
        warnings: list[str] = []
        ordered = sorted(notes, key=lambda n: n.start)
        for a, b in zip(ordered, ordered[1:]):
            if a.fret and b.fret and 0 < b.start-a.start < 0.2 and abs(a.fret-b.fret) > 8:
                warnings.append(f"{b.start:.2f} с: большой скачок руки; проверьте аппликатуру")
                b.uncertain = True
        active: list[NoteEvent] = []
        for note in ordered:
            active = [n for n in active if n.end > note.start+0.025]
            if note.string is None:
                warnings.append(f"{note.start:.2f} с: нота вне строя или недоступная аппликатура")
                continue
            for other in active:
                if other.string == note.string:
                    warnings.append(f"{note.start:.2f} с: перекрывающиеся ноты на струне {note.string}")
            active.append(note)
            active_frets = [n.fret for n in active if n.fret]
            if active_frets and max(active_frets)-min(active_frets) > 5:
                warnings.append(f"{note.start:.2f} с: большая растяжка аккорда; проверьте форму")
                note.uncertain = True
        return warnings
