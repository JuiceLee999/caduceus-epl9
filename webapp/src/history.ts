// Undo/redo over whole-pack snapshots (JSON strings). The caller mutates freely and calls commit() at the end of a
// gesture (slider release, field blur, button press): everything between two commits becomes one undo step.

export class History {
  private undos: string[] = [];
  private redos: string[] = [];
  private cur: string;

  constructor(initial: string, readonly cap = 200) { this.cur = initial; }

  /** Start over from `state` with no undo or redo steps. */
  reset(state: string) { this.cur = state; this.undos = []; this.redos = []; }

  /** Record `state` as the new current state. Returns false (and changes nothing) if it equals the current one. */
  commit(state: string): boolean {
    if (state === this.cur) return false;
    this.undos.push(this.cur);
    if (this.undos.length > this.cap) this.undos.splice(0, this.undos.length - this.cap);
    this.redos = [];
    this.cur = state;
    return true;
  }

  undo(): string | null {
    const s = this.undos.pop();
    if (s === undefined) return null;
    this.redos.push(this.cur);
    return (this.cur = s);
  }

  redo(): string | null {
    const s = this.redos.pop();
    if (s === undefined) return null;
    this.undos.push(this.cur);
    return (this.cur = s);
  }

  get current() { return this.cur; }
  get canUndo() { return this.undos.length > 0; }
  get canRedo() { return this.redos.length > 0; }
  get depth() { return this.undos.length; }
}
