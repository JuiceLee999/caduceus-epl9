// Export targets: one module per camera (or generic format). Add a module and list it in ./index.ts.
import type { Look, Pack } from '../pack';

export interface ExportFile { name: string; data: Uint8Array | string; type?: string }
export interface Target {
  id: string;                         // stable: remembered in localStorage
  label: string;                      // shown in the camera selector
  status: 'ready' | 'soon';           // 'soon' = listed but disabled
  doc?: string;                       // link with details (a port plan for 'soon' targets)
  note: string;                       // one line under the selector
  /** true, or why this look cannot be exported for this camera. */
  supports(look: Look): true | string;
  /** The files for the whole pack (throws with a readable message when the pack cannot be exported). */
  export(pack: Pack): ExportFile[];
}
