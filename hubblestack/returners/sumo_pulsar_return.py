# -*- encoding: utf-8 -*-
"""
HubbleStack Pulsar-to-sumo (http input) returner

Deliver HubbleStack Pulsar event data into sumo using the HTTP input
plugin. Required config/pillar settings:

.. code-block:: yaml

hubblestack:
  returner:
    sumo:
      - proxy: {}
        timeout: 10
        sumo_nebula_return: https://yoursumo.sumologic.com/endpointhere
        sumo_pulsar_return: https://yoursumo.sumologic.com/endpointhere
        sumo_nova_return: https://yoursumo.sumologic.com/endpointhere

"""

from collections import defaultdict

import os
import json
import requests


def _dedup_list(input_list):
    """
    Remove duplicates from the input list
    """
    deduped = []
    for idx, item in enumerate(input_list):
        if item not in input_list[idx + 1:]:
            deduped.append(item)
    return deduped


def returner(ret):
    """
    Gather pulsar data and send it to sumo
    """
    if isinstance(ret, dict) and not ret.get('return'):
        return
    data = _dedup_list(ret['return'])
    opts_list = _get_options()
    fqdn = __grains__['fqdn'] if __grains__['fqdn'] else __opts__['id']
    try:
        fqdn_ip4 = __grains__['fqdn_ip4'][0]
    except IndexError:
        fqdn_ip4 = __grains__['ipv4'][0]
    if fqdn_ip4.startswith('127.'):
        for ip4_addr in __grains__['ipv4']:
            if ip4_addr and not ip4_addr.startswith('127.'):
                fqdn_ip4 = ip4_addr
                break
    alerts = _build_alerts(data)

    # Get cloud details
    cloud_details = __grains__.get('cloud_details', {})

    for opts in opts_list:
        sumo_pulsar_return = opts['sumo_pulsar_return']
        for alert in alerts:
            if 'change' in alert:  # Linux, normal pulsar
                # The second half of the change will be '|IN_ISDIR' for directories
                change = alert['change'].split('|')[0]
                # Skip the IN_IGNORED events
                if change == 'IN_IGNORED':
                    continue
                event = _build_linux_event(alert, change)
            else:  # Windows, win_pulsar
                event = _build_windows_event(alert)
            event.update({'minion_id': __opts__['id'],
                          'dest_host': fqdn,
                          'dest_ip': fqdn_ip4})
            event.update(cloud_details)
            # publish event
            rdy = json.dumps(event)
            requests.post('{}/'.format(sumo_pulsar_return), rdy)
    return


def _get_options():
    """
    Function that aggregates the configs for sumo and returns them as a list of dicts.
    """
    if __mods__['config.get']('hubblestack:returner:sumo'):
        sumo_opts = []
        returner_opts = __mods__['config.get']('hubblestack:returner:sumo')
        if not isinstance(returner_opts, list):
            returner_opts = [returner_opts]
        for opt in returner_opts:
            processed = {'sumo_pulsar_return': opt.get('sumo_pulsar_return'),
                         'proxy': opt.get('proxy', {}),
                         'timeout': opt.get('timeout', 9.05)}
            sumo_opts.append(processed)
        return sumo_opts
    try:
        sumo_pulsar_return = __mods__['config.get']('hubblestack:returner:sumo:sumo_pulsar_return')
    except Exception:
        return None

    sumo_opts = {'sumo_pulsar_return': sumo_pulsar_return,
                 'proxy': __mods__['config.get']('hubblestack:pulsar:returner:sumo:proxy', {}),
                 'timeout': __mods__['config.get']('hubblestack:pulsar:returner:sumo:timeout',
                                                   9.05)}

    return [sumo_opts]


def _build_linux_actions():
    """
    Helper function that builds the actions defaultdict for Linux - pulsar
    """
    actions = defaultdict(lambda: 'unknown')
    actions['IN_ACCESS'] = 'read'
    actions['IN_ATTRIB'] = 'acl_modified'
    actions['IN_CLOSE_NOWRITE'] = 'read'
    actions['IN_CLOSE_WRITE'] = 'read'
    actions['IN_CREATE'] = 'created'
    actions['IN_DELETE'] = 'deleted'
    actions['IN_DELETE_SELF'] = 'deleted'
    actions['IN_MODIFY'] = 'modified'
    actions['IN_MOVE_SELF'] = 'modified'
    actions['IN_MOVED_FROM'] = 'modified'
    actions['IN_MOVED_TO'] = 'modified'
    actions['IN_OPEN'] = 'read'
    actions['IN_MOVE'] = 'modified'
    actions['IN_CLOSE'] = 'read'

    return actions


def _build_windows_actions():
    """
    Helper function that builds the actions defaultdict for Windows - win_pulsar
    """
    actions = defaultdict(lambda: 'unknown')
    actions['Delete'] = 'deleted'
    actions['Read Control'] = 'read'
    actions['Write DAC'] = 'acl_modified'
    actions['Write Owner'] = 'modified'
    actions['Synchronize'] = 'modified'
    actions['Access Sys Sec'] = 'read'
    actions['Read Data'] = 'read'
    actions['Write Data'] = 'modified'
    actions['Append Data'] = 'modified'
    actions['Read EA'] = 'read'
    actions['Write EA'] = 'modified'
    actions['Execute/Traverse'] = 'read'
    actions['Read Attributes'] = 'read'
    actions['Write Attributes'] = 'acl_modified'
    actions['Query Key Value'] = 'read'
    actions['Set Key Value'] = 'modified'
    actions['Create Sub Key'] = 'created'
    actions['Enumerate Sub-Keys'] = 'read'
    actions['Notify About Changes to Keys'] = 'read'
    actions['Create Link'] = 'created'
    actions['Print'] = 'read'

    return actions


def _build_linux_event(alert, change):
    """
    Helper function that builds the event dict on Linux hosts
    """
    if len(alert['change'].split('|')) == 2:
        object_type = 'directory'
    else:
        object_type = 'file'
    actions = _build_linux_actions()

    event = {'action': actions[change], 'change_type': 'filesystem',
             'object_category': object_type, 'object_path': alert['path'],
             'file_name': alert['name'], 'file_path': alert['tag']}
    if 'contents' in alert:
        event['contents'] = alert['contents']
    if alert['stats']:  # Gather more data if the change wasn't a delete
        stats = alert['stats']
        event['object_id'] = stats['inode']
        event['file_acl'] = stats['mode']
        event['file_create_time'] = stats['ctime']
        event['file_modify_time'] = stats['mtime']
        event['file_size'] = stats['size'] / 1024.0  # Convert bytes to kilobytes
        event['user'] = stats['user']
        event['group'] = stats['group']
        if object_type == 'file':
            event['file_hash'] = alert['checksum']
            event['file_hash_type'] = alert['checksum_type']

    return event


def _build_windows_event(alert):
    """"
    Helper function that builds the event dict on Windows hosts"
    """
    change = alert['Accesses']
    if alert['Hash'] == 'Item is a directory':
        object_type = 'directory'
    else:
        object_type = 'file'

    actions = _build_windows_actions()

    event = {'action': actions[change], 'change_type': 'filesystem',
             'object_category': object_type, 'object_path': alert['Object Name'],
             'file_name': os.path.basename(alert['Object Name']),
             'file_path': os.path.dirname(alert['Object Name'])}
    # TODO: Should we be reporting 'EntryType' or 'TimeGenerated?
    #   EntryType reports whether attempt to change was successful.

    return event


def _build_alerts(data):
    """
    Helper function that extracts all the alerts from data and returns them as a list
    """
    alerts = []
    for item in data:
        events = item
        if not isinstance(events, list):
            events = [events]
        alerts.extend(events)

    return alerts
