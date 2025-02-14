import argparse
import os
import re
from pathlib import Path

R_USED_FILE = r'used file (\d+): (.*), cost time: (.*)ms'
R_UNUSED_FILE = r'unused file (\d+): (.*), cost time: (.*)ms'
R_PARENT_MODULE = r'parentModule (\d+): (.*)'

"""
Parsing state:
0 -> 1: parse used file line.
0 -> 2: parse unused file line.
1/2 -> 3: parse parent module of used/unused file.
1/2/3 -> 0: reset to ready for next parsing.
0 -> 3: error.
"""
STATE_INIT = 0
STATE_USED = 1
STATE_UNUSED = 2
STATE_PARENT = 3

currentState = STATE_INIT

recordFiles = {}
costFiles = {}

currentFile = None

def parseArgs():
    parser = argparse.ArgumentParser('Harmony Import Analysis')
    parser.add_argument('-f', '--file', dest='file')
    parser.add_argument('-o', dest='output', default = "./result")
    return parser.parse_args()


def parseFile(filename):
    with open(filename) as file:
        while line := file.readline():
            result = handleUnusedFileLine(line)
            if not result:
                result = handleUsedFileLine(line)
            if not result:
                result = handleParentModuleLine(line)

            global currentFile
            
            if result and result['type'] == 'Used':
                stateTo(STATE_USED)
                currentFile = result['file']
                if recordFiles.get(currentFile):
                    raise RuntimeError('Duplicated used file: ' + currentFile)
                recordFiles[currentFile] = { 'data': result, 'parent': {}, 'children': {} }
            elif result and result['type'] == 'Unused':
                stateTo(STATE_UNUSED)
                currentFile = result['file']
                if recordFiles.get(currentFile):
                    raise RuntimeError('Duplicated unused file: ' + currentFile)
                recordFiles[currentFile] = { 'data': result, 'parent': {}, 'children': {} }
            elif result and result['type'] == 'Parent':
                stateTo(STATE_PARENT)
                info = recordFiles.get(currentFile)
                if not info:
                    raise RuntimeError('No current file found for parent module parsing.')

                data = result['file'].split(' ')
                if len(data) > 1:
                    methods = info['parent'].get(data[0])
                    if not methods:
                        methods = set()
                    methods.add(data[1])
                    info['parent'][data[0]] = methods
                else:
                    info['parent'][data[0]] = None
            else:
                stateTo(STATE_INIT)
                currentFile = None


def stateTo(state):
    global currentState
    if currentState == STATE_INIT:
        if state == STATE_PARENT:
            raise RuntimeError('Can not change state from INIT to PARENT.')
    elif currentState == STATE_USED:
        pass
    elif currentState == STATE_UNUSED:
        pass
    elif currentState == STATE_PARENT:
        pass 
    currentState = state


def handleUsedFileLine(line):
    info = re.findall(R_USED_FILE, line.strip())
    if len(info) > 0:
        return { 'type': 'Used', 'number': int(info[0][0]), 'file': info[0][1], 'cost': float(info[0][2]) }
    return None


def handleUnusedFileLine(line):
    info = re.findall(R_UNUSED_FILE, line.strip())
    if len(info) > 0:
        return { 'type': 'Unused', 'number': int(info[0][0]), 'file': info[0][1], 'cost': float(info[0][2]) }
    return None


def handleParentModuleLine(line):
    info = re.findall(R_PARENT_MODULE, line.strip())
    if len(info) > 0:
        return { 'type': 'Parent', 'number': int(info[0][0]), 'file': info[0][1] }
    return None


def processData():
    tempFiles = {}
    for file, data in recordFiles.items():
        for parent, methods in data['parent'].items():
            record = recordFiles.get(parent)
            if not record:
                record = tempFiles.get(parent)
            if not record:
                record = { 'data': { 'type': 'Temp', 'number': 0, 'file': parent, 'cost': 0 }, 'parent': {}, 'children': {} }
            record['children'][file] = {}
            record['children'][file]['cost'] = data['data']['cost']
            record['children'][file]['friend'] = {}

            tempFiles[parent] = record

    for file, data in tempFiles.items():
        recordFiles[file] = data

    for file, data in recordFiles.items():
        for child, cost in data['children'].items():
            updateChildrenCost(file, data, child, cost['cost'])
    updateCost()


def updateChildrenCost(file, data, childFile, childCost):
    cost = costFiles.get(file)
    if not cost:
        cost = { 'children': {} }
    else:
        if cost['children'].get(childFile):
            return

    cost['children'][childFile] = childCost

    costFiles[file] = cost

    for parent, methods in data['parent'].items():
        record = recordFiles.get(parent)
        if record:
            updateChildrenCost(parent, record, childFile, childCost)


def updateCost():
    for file, data in costFiles.items():
        totalCost = 0
        for child, cost in data['children'].items():
            totalCost += cost
        data['cost'] = totalCost

    for file, data in recordFiles.items():
        cost = costFiles.get(file)
        if cost:
            data['cost'] = data['data']['cost'] + cost['cost']
        else:
            data['cost'] = data['data']['cost']

        for child, childCost in data['children'].items():
            cost = costFiles.get(child)
            if cost:
                childCost['cost'] += cost['cost']
                for friend, _ in data['children'].items():
                    if child == friend:
                        continue
                    friendCost = costFiles.get(friend)
                    if friendCost:
                        (unionType, totalCost) = getUnionChildrenCost(child, cost, friend, friendCost)
                        if unionType > 0:
                            childCost['friend'][friend] = {}
                            childCost['friend'][friend]['cost'] = totalCost
                            if unionType == 1:
                                childCost['friend'][friend]['type'] = 'In'
                            elif unionType == 2:
                                childCost['friend'][friend]['type'] = 'Out'
                            elif unionType == 3:
                                childCost['friend'][friend]['type'] = 'Shared'
                            else:
                                childCost['friend'][friend]['type'] = 'Unknown'


def getUnionChildrenCost(file, cost, friendFile, friendCost):
    # 0: unknown
    # 1: in
    # 2: out
    # 3: shared
    unionType = 0
    totalCost = 0
    if cost['children'].get(friendFile):
        unionType = 1
        totalCost += recordFiles[friendFile]['data']['cost']
    if friendCost['children'].get(file):
        unionType = 2
        totalCost += recordFiles[file]['data']['cost']
    for f, c in cost['children'].items():
        if f == friendFile:
            continue
        if friendCost['children'].get(f):
            if unionType == 0:
                unionType = 3
            totalCost += c

    return (unionType, totalCost)


def printData(output):
    try:
        os.mkdir(output)
    except Exception as e:
        pass

    with open(Path(output) / 'result_tree', 'w') as f:
        for file, data in recordFiles.items():
            f.write('({}) {} {}'.format(data['data']['type'], file, data['cost']))
            f.write('\n')
            f.write('  Parents:')
            f.write('\n')
            if len(data['parent']) > 0:
                for parentFile, parentData in data['parent'].items():
                    type = 'Unknown'
                    parent = recordFiles.get(parentFile)
                    if parent:
                        type = parent['data']['type']
                    f.write('    |-> ({}) {}'.format(type, parentFile))
                    if parentData:
                        for method in parentData:
                            f.write(' {}'.format(method))
                    f.write('\n')
            else:
                f.write('    |-> (Empty)')
                f.write('\n')
            f.write('  Children:')
            f.write('\n')
            if len(data['children']) > 0:
                for childFile, childData in data['children'].items():
                    type = 'Unknown'
                    child = recordFiles.get(childFile)
                    if child:
                        type = child['data']['type']
                    f.write('    |-> ({}) {} {}'.format(type, childFile, childData['cost']))
                    f.write('\n')
                    for friendFile, friendData in childData['friend'].items():
                        f.write('      |-> ({}) {} {}'.format(friendData['type'], friendFile, friendData['cost']))
                        f.write('\n')
            else:
                f.write('    |-> (Empty)')
                f.write('\n')
            f.write('\n\n')

    with open(Path(output) / 'result_cost.csv', 'w') as f:
        f.write('Type;File;Cost;Parent;Children')
        f.write('\n')
        for file, data in recordFiles.items():
            f.write('{};{};{};{};{}'.format(data['data']['type'], file, data['cost'], len(data['parent']), len(data['children'])))
            f.write('\n')


if __name__ == '__main__':
    args = parseArgs()
    parseFile(args.file)
    processData()
    printData(args.output)
