import { describe, expect, it } from 'vitest';
import { History } from '../src/history';

describe('History', () => {
  it('undoes and redoes in order', () => {
    const h = new History('a');
    h.commit('b'); h.commit('c');
    expect([h.canUndo, h.canRedo]).toEqual([true, false]);
    expect(h.undo()).toBe('b');
    expect(h.undo()).toBe('a');
    expect(h.undo()).toBeNull();
    expect(h.current).toBe('a');
    expect(h.redo()).toBe('b');
    expect(h.redo()).toBe('c');
    expect(h.redo()).toBeNull();
  });

  it('coalesces: states between commits are one step; an unchanged commit is not a step', () => {
    const h = new History('0');
    // a slider drag 0 -> 1 -> 2 -> 3 commits only on release
    let drag = '0';
    for (const v of ['1', '2', '3']) drag = v;
    expect(h.commit(drag)).toBe(true);
    expect(h.commit('3')).toBe(false);
    expect(h.depth).toBe(1);
    expect(h.undo()).toBe('0');
    expect(h.canUndo).toBe(false);
  });

  it('a new edit after undo clears redo', () => {
    const h = new History('a');
    h.commit('b'); h.commit('c');
    h.undo();
    expect(h.canRedo).toBe(true);
    h.commit('x');
    expect(h.canRedo).toBe(false);
    expect(h.redo()).toBeNull();
    expect(h.undo()).toBe('b');
  });

  it('caps the number of undo steps, dropping the oldest', () => {
    const h = new History('s0', 200);
    for (let i = 1; i <= 250; i++) h.commit(`s${i}`);
    expect(h.depth).toBe(200);
    let last = '';
    for (let s = h.undo(); s !== null; s = h.undo()) last = s;
    expect(last).toBe('s50');
  });

  it('reset forgets all steps', () => {
    const h = new History('a');
    h.commit('b'); h.undo();
    h.reset('z');
    expect([h.current, h.canUndo, h.canRedo]).toEqual(['z', false, false]);
  });
});
