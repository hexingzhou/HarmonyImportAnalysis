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
relationFiles = {}
testSet = set()

currentFile = None

def parseArgs():
    parser = argparse.ArgumentParser('Harmony Import Analysis')
    parser.add_argument('-f', '--file', dest='file')
    parser.add_argument('-t', '--test', dest='test')
    parser.add_argument('-o', dest='output', default = "./result")
    return parser.parse_args()


def parseTest(filename):
    if filename is None:
        return
    with open(filename) as file:
        while line := file.readline():
            testSet.add(line.strip())


def parseFile(filename):
    with open(filename) as file:
        while line := file.readline():
            result = handleUnusedFileLine(line)
            if result is None:
                result = handleUsedFileLine(line)
            if result is None:
                result = handleParentModuleLine(line)

            global currentFile
            
            if result is not None and result['type'] == 'Used':
                stateTo(STATE_USED)
                currentFile = result['file']
                if currentFile in recordFiles:
                    raise RuntimeError('Duplicated used file: ' + currentFile)
                recordFiles[currentFile] = { 'data': result, 'parent': {}, 'children': {} }
            elif result is not None and result['type'] == 'Unused':
                stateTo(STATE_UNUSED)
                currentFile = result['file']
                if currentFile in recordFiles:
                    raise RuntimeError('Duplicated unused file: ' + currentFile)
                recordFiles[currentFile] = { 'data': result, 'parent': {}, 'children': {} }
            elif result is not None and result['type'] == 'Parent':
                stateTo(STATE_PARENT)
                info = recordFiles.get(currentFile)
                if info is None:
                    raise RuntimeError('No current file found for parent module parsing.')

                data = result['file'].split(' ')
                if len(data) > 1:
                    methods = info['parent'].get(data[0])
                    if methods is None:
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
            if record is None:
                record = tempFiles.get(parent)
            if record is None:
                record = { 'data': { 'type': 'Temp', 'number': 0, 'file': parent, 'cost': 0 }, 'parent': {}, 'children': {} }
                tempFiles[parent] = record

            record['children'][file] = {}
            record['children'][file]['type'] = data['data']['type']

    for file, data in tempFiles.items():
        recordFiles[file] = data

    for file, data in recordFiles.items():
        for childFile, _ in data['children'].items():
            if childFile in recordFiles:
                updateChildren(file, data, childFile, 0)
    updateRelationShip()
    updateCost()


def updateChildren(file, data, childFile, index):
    if file == childFile:
        return
    children = relationFiles.get(file)
    if children is None:
        children = {}
        relationFiles[file] = children
    else:
        if childFile in children:
            return

    children[childFile] = 'Unknown'

    for parentFile, _ in data['parent'].items():
        if parentFile in recordFiles:
            updateChildren(parentFile, recordFiles.get(parentFile), childFile, index + 1)


def updateRelationShip():
    for parent, children in relationFiles.items():
        for child, type in children.items():
            if type == 'Unknown':
                record = recordFiles.get(child)
                if record is not None:
                    isSingle = True
                    for parentFile, _ in record['parent'].items():
                        if parent == parentFile:
                            continue
                        if parentFile in children:
                            continue
                        isSingle = False
                    if isSingle:
                        children[child] = 'Single'
                    else:
                        children[child] = 'Shared'
                        later = relationFiles.get(child)
                        if later is not None:
                            for c, _ in later.items():
                                if c in children:
                                    children[c] = 'Shared'


def updateCost():
    for parent, children in relationFiles.items():
        parentData = recordFiles.get(parent)
        if parentData is None:
            continue
        cost = parentData['data']['cost']
        for child, type in children.items():
            if type == 'Unknown':
                raise RuntimeError('Unknown type of child(' + child + ') in parent(' + parent + ')')
            if type == 'Single':
                childData = recordFiles.get(child)
                if childData is None:
                    continue
                cost += childData['data']['cost']
        parentData['cost'] = cost

    for parent, parentData in recordFiles.items():
        cost = parentData.get('cost')
        if cost is None:
            parentData['cost'] = 0

    for parent, parentData in recordFiles.items():
        for child, childInfo in parentData['children'].items():
            childData = recordFiles.get(child)
            if childData is not None:
                childInfo['cost'] = childData['cost']


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


def printTest():
    children = {}
    for test in testSet:
        c = relationFiles.get(test)
        if c is not None:
            for child, _ in c.items():
                children[child] = 'Unknown'

    for child, type in children.items():
        if type == 'Unknown':
            record = recordFiles.get(child)
            if record is not None:
                isSingle = True
                for parentFile, _ in record['parent'].items():
                    if parentFile in testSet:
                        continue
                    if parentFile in children:
                        continue
                    isSingle = False
                if isSingle:
                    children[child] = 'Single'
                else:
                    children[child] = 'Shared'
                    later = relationFiles.get(child)
                    if later is not None:
                        for c, _ in later.items():
                            if c in children:
                                children[c] = 'Shared'

    cost = 0
    for child, type in children.items():
        if type == 'Single':
            childData = recordFiles.get(child)
            if childData is None:
                continue
            cost += childData['data']['cost']
    for test in testSet:
        testData = recordFiles.get(test)
        if testData is None:
            continue
        cost += testData['data']['cost']

    print('cost: ' + str(cost))


if __name__ == '__main__':
    args = parseArgs()
    parseFile(args.file)
    processData()
    printData(args.output)
    parseTest(args.test)
    printTest()
