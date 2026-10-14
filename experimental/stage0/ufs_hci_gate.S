// SPDX-License-Identifier: GPL-2.0-only
//
// TreeForge Stage-0 — exact GS201/Linux UFS TUR descriptor.
//
// Exact modern Linux contract:
//
//   UTRD DW0:
//     UTP_CMD_TYPE_UFS_STORAGE == 1
//     command type field << 28 == 0x10000000
//     no data transfer
//
//   UCD:
//     command UPIU  = 512 bytes
//     response UPIU = 512 bytes
//
// GS201 has fixed-prdt-req_list-ocs, so geometry uses
// normal dword granularity:
//
//   response length = 512 / 4  = 0x80
//   response offset = 512 / 4  = 0x80
//   PRDT offset     = 1024 / 4 = 0x100
//   PRDT length     = 0
//
// Therefore:
//
//   DW6 = 0x00800080
//   DW7 = 0x01000000
//
// Command:
//   SCSI TEST UNIT READY
//   LUN 0
//   no data phase
//   no PRDT entries
//
// Completion criterion for this gate:
//   UTRLDBR slot0 clears.
//
// No interrupt-status dependency.
// No cancellation.
// No OCS success check.
// No cache-maintenance experiment.
// No media read/write.
// x0-x3 preserved.

    .section .text, "ax", %progbits
    .balign 4

    .global treeforge_stage0_ufs_tur_exact_geometry
    .type treeforge_stage0_ufs_tur_exact_geometry, %function

    .equ TF_HCS,       0x30
    .equ TF_HCE,       0x34
    .equ TF_UTRLBA,    0x50
    .equ TF_UTRLBAU,   0x54
    .equ TF_UTRLDBR,   0x58
    .equ TF_UTRLRSR,   0x60

treeforge_stage0_ufs_tur_exact_geometry:

    movz    x11, #0x1470, lsl #16

    // Established hardware-ready contract.
    ldr     w12, [x11, #TF_HCE]
    tbz     w12, #0, .Lfail

    ldr     w13, [x11, #TF_HCS]
    and     w14, w13, #0xf
    cmp     w14, #0xf
    b.ne    .Lfail

    ldr     w12, [x11, #TF_UTRLRSR]
    tbz     w12, #0, .Lfail

    ldr     w13, [x11, #TF_UTRLDBR]
    cbnz    w13, .Lfail

    // Bootloader UTRL base.
    ldr     w14, [x11, #TF_UTRLBA]
    ldr     w15, [x11, #TF_UTRLBAU]
    orr     x16, x14, x15, lsl #32

    cbz     x16, .Lfail
    tst     x16, #0x3ff
    b.ne    .Lfail

    // Slot-0 UCD base.
    ldr     w17, [x16, #0x10]
    ldr     w18, [x16, #0x14]
    orr     x19, x17, x18, lsl #32

    cbz     x19, .Lfail

    //
    // SCSI TEST UNIT READY UPIU.
    //
    // Entire 32-byte command UPIU is zero first.
    // TUR CDB itself is all-zero.
    //
    stp     xzr, xzr, [x19, #0x00]
    stp     xzr, xzr, [x19, #0x10]

    // UPIU byte 0 = UPIU_TRANSACTION_COMMAND = 0x01.
    movz    w21, #0x0001
    str     w21, [x19, #0x00]

    //
    // Exact modern Linux UTRD header.
    //
    // UTP_CMD_TYPE_UFS_STORAGE = 1 << 28
    // no-data direction        = 0
    //
    movz    w21, #0x1000, lsl #16
    str     w21, [x16, #0x00]

    // DW1 reserved.
    str     wzr, [x16, #0x04]

    // DW2 = OCS_INVALID_COMMAND_STATUS.
    movz    w21, #0x000f
    str     w21, [x16, #0x08]

    // DW3 reserved / crypto unused.
    str     wzr, [x16, #0x0c]

    //
    // Exact fixed GS201 command-descriptor geometry.
    //
    // DW6:
    //   response_upiu_length = 0x0080 dwords
    //   response_upiu_offset = 0x0080 dwords
    //
    // LE 32-bit value = 0x00800080.
    //
    movz    w25, #0x0080
    movk    w25, #0x0080, lsl #16
    str     w25, [x16, #0x18]

    //
    // DW7:
    //   prd_table_length = 0
    //   prd_table_offset = 0x0100 dwords
    //
    // LE 32-bit value = 0x01000000.
    //
    movz    w25, #0x0000
    movk    w25, #0x0100, lsl #16
    str     w25, [x16, #0x1c]

    dsb     sy

    //
    // Submit slot 0.
    //
    movz    w21, #0x0001
    str     w21, [x11, #TF_UTRLDBR]

    //
    // Bounded DBR retirement poll.
    //
    movz    w22, #0xffff
    movk    w22, #0x00ff, lsl #16

.Lpoll:
    ldr     w23, [x11, #TF_UTRLDBR]
    tbz     w23, #0, .Lcomplete

    subs    w22, w22, #1
    b.ne    .Lpoll
    b       .Lfail

.Lcomplete:
    dsb     sy

    //
    // Stage-0 RVA = 0x021e8a00
    // ADR offset  = 0xc0
    // PC RVA      = 0x021e8ac0
    //
    adr     x9, .

    movz    x10, #0x8ac0
    movk    x10, #0x021e, lsl #16
    sub     x9, x9, x10

    // Original Linux entry RVA = 0x01bda3bc.
    movz    x10, #0xa3bc
    movk    x10, #0x01bd, lsl #16

    add     x10, x9, x10
    br      x10

.Lfail:
    wfe
    b       .Lfail

    .size treeforge_stage0_ufs_tur_exact_geometry, . - treeforge_stage0_ufs_tur_exact_geometry
