#!/usr/bin/python3
"""Project-local Docker shim; never changes daemon or other projects."""
import os
import sys
args=sys.argv[1:]
if args and args[0]=='run':
    name=os.environ.get('CHIPFORGE_CONTAINER_NAME')
    if not name or not name.startswith('chipforge-'):
        raise SystemExit('Missing project-owned container identity')
    if '--name' in args:
        at=args.index('--name')
        args[at+1]=name
    else:
        args[1:1]=['--name',name]
    args[1:1]=['--cpus','8','--memory','24g','--pids-limit','1024','-e','_OPENLANE_MAX_CORES=8']
    # The matching SKY130HD PDK is provisioned and locked in this project.
    # Use LibreLane's supported manual-PDK mode, avoiding its default download
    # of unrelated IO, SRAM and analog libraries inside a network-less container.
    for at,value in enumerate(args):
        if value=='librelane' and at>0 and args[at-1]=='-m':
            args[at+1:at+1]=['--manual-pdk','-j','8']
            break
os.execv('/usr/bin/docker',['docker',*args])
