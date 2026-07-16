#!/usr/bin/env bash
# Fixed HP 240 G4 / Broadwell compile-time pruning shared by both kernel lines.

notebook_symbol_allowed() {
  local candidate="$1"
  shift
  local allowed
  for allowed in "$@"; do
    [[ "$candidate" == "$allowed" ]] && return 0
  done
  return 1
}

notebook_kconfig_symbols() {
  local tree="$1"
  grep -RhoE --include='Kconfig*' \
    '^[[:space:]]*(menu)?config[[:space:]]+[A-Z0-9_]+' "$tree" 2>/dev/null \
    | awk '{print $2}' | sort -u
}

notebook_disable_tree_except() {
  local tree="$1"
  shift
  local symbol
  while IFS= read -r symbol; do
    notebook_symbol_allowed "$symbol" "$@" || scripts/config --disable "$symbol"
  done < <(notebook_kconfig_symbols "$tree")
}

notebook_disable_prefix_except() {
  local tree="$1" prefix="$2"
  shift 2
  local symbol
  while IFS= read -r symbol; do
    [[ "$symbol" == "$prefix"* ]] || continue
    notebook_symbol_allowed "$symbol" "$@" || scripts/config --disable "$symbol"
  done < <(notebook_kconfig_symbols "$tree")
}

notebook_assert_enabled() {
  local symbol="$1"
  if ! grep -Eq "^CONFIG_${symbol}=[ym]$" .config; then
    echo "Required notebook driver is not enabled: CONFIG_${symbol}" >&2
    grep -E "^CONFIG_${symbol}=" .config >&2 || true
    return 1
  fi
}

notebook_assert_tree_except() {
  local tree="$1"
  shift
  local symbol
  while IFS= read -r symbol; do
    notebook_symbol_allowed "$symbol" "$@" && continue
    if grep -Eq "^CONFIG_${symbol}=[ym]$" .config; then
      echo "Unexpected driver survived notebook pruning: CONFIG_${symbol}" >&2
      return 1
    fi
  done < <(notebook_kconfig_symbols "$tree")
}

notebook_assert_prefix_except() {
  local tree="$1" prefix="$2"
  shift 2
  local symbol
  while IFS= read -r symbol; do
    [[ "$symbol" == "$prefix"* ]] || continue
    notebook_symbol_allowed "$symbol" "$@" && continue
    if grep -Eq "^CONFIG_${symbol}=[ym]$" .config; then
      echo "Unexpected driver survived notebook pruning: CONFIG_${symbol}" >&2
      return 1
    fi
  done < <(notebook_kconfig_symbols "$tree")
}

NOTEBOOK_DISABLED_SYMBOLS=(
  COMPILE_TEST KUNIT KUNIT_ALL_TESTS MAC80211_HWSIM
  STAGING COMEDI IIO I3C MTD INFINIBAND
  CXL_BUS CXL_PCI CXL_ACPI CXL_PMEM CXL_MEM_RAW_COMMANDS CXL_REGION
  LIBNVDIMM ACPI_NFIT X86_PMEM_LEGACY NVDIMM_PFN NVDIMM_DAX DEV_DAX DEV_DAX_PMEM DEV_DAX_CXL
  NTB RAPIDIO VME_BUS IPACK_BUS PCCARD PCMCIA FIREWIRE THUNDERBOLT
  CAN NFC IEEE802154 6LOWPAN HAMRADIO ATM FDDI HIPPI ISDN
  SND_SOC SND_FIREWIRE SND_PCMCIA SND_ISA
  SCSI_LOWLEVEL SCSI_TAPE SCSI_SAS_LIBSAS SCSI_SAS_ATA SCSI_SAS_HOST_SMP
  SCSI_FC_ATTRS SCSI_ISCSI_ATTRS ISCSI_TCP LIBFC LIBFCOE FCOE TARGET_CORE
  NET_DSA NET_VENDOR_AMAZON NET_VENDOR_AQUANTIA NET_VENDOR_BROCADE
  NET_VENDOR_CAVIUM NET_VENDOR_CHELSIO NET_VENDOR_FUNGIBLE NET_VENDOR_GOOGLE
  NET_VENDOR_HUAWEI NET_VENDOR_MELLANOX NET_VENDOR_NETRONOME
  NET_VENDOR_PENSANDO NET_VENDOR_QLOGIC NET_VENDOR_SFC
  DRM_XE DRM_NOUVEAU DRM_AST DRM_MGAG200 DRM_QXL DRM_VMWGFX
  DRM_VIRTIO_GPU DRM_BOCHS DRM_CIRRUS_QEMU DRM_HYPERV DRM_XEN_FRONTEND DRM_VKMS
)

apply_notebook_prune_profile() {
  NOTEBOOK_BASELINE_MODULES="$(grep -c '=m$' .config || true)"
  NOTEBOOK_BASELINE_BUILTINS="$(grep -c '=y$' .config || true)"

  # Keep only the UVC webcam path inside the otherwise enormous media tree.
  scripts/config --module MEDIA_SUPPORT
  scripts/config --enable MEDIA_SUPPORT_FILTER
  scripts/config --disable MEDIA_SUBDRV_AUTOSELECT
  scripts/config --enable MEDIA_CAMERA_SUPPORT
  scripts/config --enable MEDIA_USB_SUPPORT
  scripts/config --module VIDEO_DEV
  scripts/config --module USB_VIDEO_CLASS
  scripts/config --enable MEDIA_CONTROLLER
  for symbol in \
    MEDIA_ANALOG_TV_SUPPORT MEDIA_DIGITAL_TV_SUPPORT MEDIA_RADIO_SUPPORT \
    MEDIA_SDR_SUPPORT MEDIA_PLATFORM_SUPPORT MEDIA_PCI_SUPPORT MEDIA_TEST_SUPPORT \
    VIDEO_CAMERA_SENSOR USB_GSPCA USB_PWC VIDEO_S2255 VIDEO_USBTV VIDEO_EM28XX \
    MEDIA_CEC_RC RC_CORE RC_MAP RC_DECODERS RC_DEVICES; do
    scripts/config --disable "$symbol"
  done

  for symbol in "${NOTEBOOK_DISABLED_SYMBOLS[@]}"; do
    scripts/config --disable "$symbol"
  done

  # x86 RTC: keep the PC CMOS clock, remove PMIC/SPI/I2C RTC farms.
  notebook_disable_prefix_except drivers/rtc RTC_DRV_ RTC_DRV_CMOS
  scripts/config --enable RTC_CLASS
  scripts/config --enable RTC_DRV_CMOS

  # Keep useful laptop telemetry only: CPU, ACPI power and disk temperature.
  notebook_disable_tree_except drivers/hwmon \
    HWMON SENSORS_CORETEMP SENSORS_ACPI_POWER SENSORS_DRIVETEMP
  scripts/config --module HWMON
  scripts/config --module SENSORS_CORETEMP
  scripts/config --module SENSORS_ACPI_POWER
  scripts/config --module SENSORS_DRIVETEMP

  # Broadwell uses Intel I801 SMBus; retain DesignWare for LPSS/I2C-HID paths.
  notebook_disable_tree_except drivers/i2c/busses \
    I2C_I801 I2C_I801_MUX I2C_CCGX_UCSI I2C_DESIGNWARE_CORE I2C_DESIGNWARE_PLATFORM I2C_DESIGNWARE_PCI I2C_SCMI
  scripts/config --module I2C_I801
  scripts/config --module I2C_DESIGNWARE_PLATFORM
  scripts/config --module I2C_DESIGNWARE_PCI
  scripts/config --module I2C_SCMI

  # Keep only the Intel TCO watchdog path.
  notebook_disable_tree_except drivers/watchdog \
    WATCHDOG WATCHDOG_CORE WATCHDOG_HANDLE_BOOT_ENABLED WATCHDOG_OPEN_TIMEOUT \
    WATCHDOG_NOWAYOUT WATCHDOG_SYSFS ITCO_WDT ITCO_VENDOR_SUPPORT SOFT_WATCHDOG
  scripts/config --enable WATCHDOG
  scripts/config --module ITCO_WDT

  # HP ships this model with Realtek HDA plus Intel display audio. Preserve HDA
  # and USB headsets; remove the large ASoC SoC/DSP codec matrix.
  scripts/config --enable SND
  scripts/config --module SND_HDA_INTEL
  scripts/config --module SND_HDA_CODEC_REALTEK
  scripts/config --module SND_HDA_CODEC_HDMI
  scripts/config --module SND_USB_AUDIO
}

verify_notebook_prune_profile() {
  local symbol
  assert_config "CONFIG_MEDIA_SUPPORT=m"
  assert_config "CONFIG_MEDIA_SUPPORT_FILTER=y"
  assert_config "CONFIG_MEDIA_CAMERA_SUPPORT=y"
  assert_config "CONFIG_MEDIA_USB_SUPPORT=y"
  assert_config "CONFIG_VIDEO_DEV=m"
  assert_config "CONFIG_USB_VIDEO_CLASS=m"
  assert_config "CONFIG_MEDIA_CONTROLLER=y"

  for symbol in \
    MEDIA_SUBDRV_AUTOSELECT MEDIA_ANALOG_TV_SUPPORT MEDIA_DIGITAL_TV_SUPPORT \
    MEDIA_RADIO_SUPPORT MEDIA_SDR_SUPPORT MEDIA_PLATFORM_SUPPORT MEDIA_PCI_SUPPORT \
    MEDIA_TEST_SUPPORT VIDEO_CAMERA_SENSOR USB_GSPCA USB_PWC VIDEO_S2255 \
    VIDEO_USBTV VIDEO_EM28XX MEDIA_CEC_RC RC_CORE RC_MAP RC_DECODERS RC_DEVICES; do
    assert_disabled_or_absent "$symbol"
  done
  for symbol in "${NOTEBOOK_DISABLED_SYMBOLS[@]}"; do
    assert_disabled_or_absent "$symbol"
  done

  notebook_assert_enabled RTC_CLASS
  notebook_assert_enabled RTC_DRV_CMOS
  notebook_assert_enabled HWMON
  notebook_assert_enabled SENSORS_CORETEMP
  notebook_assert_enabled I2C_I801
  notebook_assert_enabled SND_HDA_INTEL
  notebook_assert_enabled SND_HDA_CODEC_REALTEK
  notebook_assert_enabled SND_HDA_CODEC_HDMI
  notebook_assert_enabled SND_USB_AUDIO

  notebook_assert_prefix_except drivers/rtc RTC_DRV_ RTC_DRV_CMOS
  notebook_assert_tree_except drivers/hwmon \
    HWMON SENSORS_CORETEMP SENSORS_ACPI_POWER SENSORS_DRIVETEMP
  notebook_assert_tree_except drivers/i2c/busses \
    I2C_I801 I2C_I801_MUX I2C_CCGX_UCSI I2C_DESIGNWARE_CORE I2C_DESIGNWARE_PLATFORM I2C_DESIGNWARE_PCI I2C_SCMI
  notebook_assert_tree_except drivers/watchdog \
    WATCHDOG WATCHDOG_CORE WATCHDOG_HANDLE_BOOT_ENABLED WATCHDOG_OPEN_TIMEOUT \
    WATCHDOG_NOWAYOUT WATCHDOG_SYSFS ITCO_WDT ITCO_VENDOR_SUPPORT SOFT_WATCHDOG
}

write_notebook_prune_profile() {
  {
    echo "Profile: HP 240 G4 fixed-notebook compile pruning"
    echo "Baseline modules: ${NOTEBOOK_BASELINE_MODULES:-unknown}"
    echo "Final modules: $(grep -c '=m$' .config || true)"
    echo "Baseline built-ins: ${NOTEBOOK_BASELINE_BUILTINS:-unknown}"
    echo "Final built-ins: $(grep -c '=y$' .config || true)"
    echo "Preserved: UVC, CMOS RTC, Intel I801/DesignWare I2C, coretemp/drivetemp, Intel/optional AMD graphics, HDA/USB audio"
    echo "Disabled: media broadcast/capture farms, staging, IIO/Comedi, MTD/I3C, RDMA/CXL/NVDIMM, legacy buses/protocols, enterprise storage/networking, ASoC and virtual/server GPUs"
  } | tee "$LOGDIR/notebook-prune-profile.txt"
}
