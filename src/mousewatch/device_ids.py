"""Central catalog of USB vendor/product identifiers used by MouseWatch.

Keep protocol-specific VID/PID values in this file so new device support is a
single-file update.
"""

# MCHOSE ecosystem vendor IDs observed for wireless dongles.
MCHOSE_VENDOR_IDS: tuple[int, ...] = (
    0x3837,
    0x41E4,
    0x0BDA,
    0x5253,
)

# ATK ecosystem IDs (ATK A9 Plus and its NANO dongle).
ATK_VENDOR_ID: int = 0x373B
ATK_PRODUCT_ID_WIRELESS_DONGLE: int = 0x10C9
ATK_PRODUCT_ID_WIRED_MOUSE: int = 0x1115
ATK_PRODUCT_IDS: tuple[int, ...] = (
    ATK_PRODUCT_ID_WIRELESS_DONGLE,
    ATK_PRODUCT_ID_WIRED_MOUSE,
)
