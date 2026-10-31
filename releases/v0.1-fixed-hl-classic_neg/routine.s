/* E-P7 1.1 "fixed H/L" patch: after the stock COLOR builder, overwrite the
 * 12 output records' hue (+18) and lightness (+22) coefficients with
 * constants from a recipe. Saturation, LUTs and control word untouched.
 * Reached only on the COLOR picture-mode path (selector 0x603b0252).
 * Our own code (ep7-firmware); design informed by fishcu's PEN-F patch.
 */
 .am33_2
 .text
 .global _start
_start:
 call ep7_builder,[d2,d3,a2,a3],96   /* displaced stock instruction */
 /* inline frame (no second CALL: keeps MDR); a2 = context (callee-saved) */
 add -16,sp
 mov d0,(0,sp)
 mov d1,(4,sp)
 mov a0,(8,sp)
 mov a1,(12,sp)
 mov (12,a2),a0          /* output block */
 add 706,a0        /* -> record 0 hue (+688+18) */
 mov hl_table,a1
 mov 12,d1
1:
 movhu (a1),d0
 movhu d0,(a0)           /* hue */
 movhu (2,a1),d0
 movhu d0,(4,a0)         /* lightness (+22 = hue+4) */
 add 4,a1
 add 24,a0
 add -1,d1
 bne 1b
 mov (0,sp),d0
 mov (4,sp),d1
 mov (8,sp),a0
 mov (12,sp),a1
 add 16,sp
 jmp ep7_resume

 .balign 2
hl_table:   /* physical record order: (hue_native, light_native) x 12 */
 .hword 0,-150   /* rec 0 */
 .hword 0,-100   /* rec 1 */
 .hword -7000,-25   /* rec 2 */
 .hword 2000,50   /* rec 3 */
 .hword -6000,-25   /* rec 4 */
 .hword -5000,-200   /* rec 5 */
 .hword 1000,-150   /* rec 6 */
 .hword 0,-50   /* rec 7 */
 .hword -6000,50   /* rec 8 */
 .hword 3000,100   /* rec 9 */
 .hword -7000,-100   /* rec 10 */
 .hword -2000,-200   /* rec 11 */
