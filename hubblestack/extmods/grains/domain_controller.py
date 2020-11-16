"""
HubbleStack domain controller Grain.
CLI Usage - hubble grains.get domain_controller
Example Output - {u'is_domain_controller': True}
Author - Mudit Agarwal (muagarwa@adobe.com)
"""
import salt.utils.platform
import logging
import salt.modules.reg
__virtualname__ = "domain_controller"

__salt__ = {'reg.read_value': salt.modules.reg.read_value}

log = logging.getLogger(__name__)


def __virtual__():
  """
  Load domain controller grains
  """

  if not salt.utils.platform.is_windows():
    return False, "domain_controller: Not available on Linux"
  return __virtualname__


def is_domain_controller():
    ret = __salt__['reg.read_value'](hive="HKLM",
                                     key=r"SYSTEM\CurrentControlSet\Control\ProductOptions",
                                     vname="ProductType")
    if ret['vdata'] == "LanmanNT":
        return { "is_domain_controller": True}
    else:
        return { "is_domain_controller": False}