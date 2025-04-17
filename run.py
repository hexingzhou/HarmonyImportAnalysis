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
moduleFiles = {}
entryFiles = {}

entrySet = set()

currentFile = None

def parseArgs():
    parser = argparse.ArgumentParser('Harmony Import Analysis')
    parser.add_argument('-f', '--file', dest='file')
    parser.add_argument('-e', '--entry', dest='entry')
    parser.add_argument('-i', '--index', dest='index', type=int, default=10)
    parser.add_argument('-p', '--point', dest='point', default='')
    parser.add_argument('-c', '--count', dest='count', type=int, default=0)
    parser.add_argument('-o', '--output',dest='output', default="./result")
    return parser.parse_args()


def parseEntry(filename):
    if filename is None:
        return
    with open(filename) as file:
        while line := file.readline():
            line = line.strip()
            if line.startswith('//') or line.startswith('#'):
                continue
            entrySet.add(line)


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

    updateRelation()
    updateRecordCost()


def processEntryData(count):
    updateEntry(count)


def processModuleData(point, index):
    points = point.split('/')
    for file, data in recordFiles.items():
        array = file.split('/')
        path = ''
        i = 0
        p = True
        for step in array:
            if step in points:
                p = False
            if i > index:
                p = False
            if i > 0:
                path = path + '/'
            path = path + step
            moduleData = moduleFiles.get(path)
            if moduleData is None:
                moduleData = {'index': i, 'files': set(), 'cost': 0, 'used': 0, 'unused': 0, 'point': p}
                moduleFiles[path] = moduleData
            moduleData['files'].add(file)
            moduleData['cost'] += data['data']['cost']
            if data['data']['type'] == 'Used':
                moduleData['used'] += data['data']['cost']
            elif data['data']['type'] == 'Unused':
                moduleData['unused'] += data['data']['cost']
            i += 1


def updateRelation():
    for file, data in recordFiles.items():
        for childFile, _ in data['children'].items():
            if childFile in recordFiles:
                collectChildrenInRelation(file, data, childFile)
    
    for parent, children in relationFiles.items():
        parentData = recordFiles.get(parent)
        if parentData is None:
            raise RuntimeError('No record of ' + parent)

        for child, _ in parentData['children'].items():
            findShareTypeInRelation(parent, children, child)


def collectChildrenInRelation(parent, parentData, child):
    if parent == child:
        return

    children = relationFiles.get(parent)
    if children is None:
        children = {}
        relationFiles[parent] = children
    else:
        if child in children:
            return

    children[child] = 'Unknown'

    for parentFile, _ in parentData['parent'].items():
        if parentFile in recordFiles:
            collectChildrenInRelation(parentFile, recordFiles.get(parentFile), child)


def findShareTypeInRelation(parent, children, child):
    # Check child.
    if children[child] == 'Unknown':
        record = recordFiles.get(child)
        if record is None:
            children[child] = 'Single'
            return
        single = True
        for parentFile, _ in record['parent'].items():
            if parent == parentFile:
                continue
            if parentFile in children:
                continue
            single = False
        if single:
            children[child] = 'Single'
            # Continue check children of the child.
            for childFile, _ in record['children'].items():
                if childFile in children:
                    findShareTypeInRelation(parent, children, childFile)
        else:
            children[child] = 'Shared'
            for childFile, _ in record['children'].items():
                if childFile in children:
                    setSharedInRelation(parent, children, childFile)


def setSharedInRelation(parent, children, child):
    if children[child] == 'Unknown':
        children[child] = 'Shared'
        record = recordFiles.get(child)
        if record is None:
            return
        for childFile, _ in record['children'].items():
            if childFile in children:
                setSharedInRelation(parent, children, childFile)


def updateRecordCost():
    for parent, parentData in recordFiles.items():
        cost = parentData['data']['cost']
        children = relationFiles.get(parent)
        if children is not None:
            for child, relation in children.items():
                if relation == 'Unknown':
                    raise RuntimeError('Unknown relation type of child(' + child + ') in parent(' + parent + ')')
                if relation == 'Single':
                    childData = recordFiles.get(child)
                    if childData is not None:
                        cost += childData['data']['cost']
        parentData['cost'] = cost

    # Copy parent cost to the children of other parents in record list.
    for parent, parentData in recordFiles.items():
        for child, childInfo in parentData['children'].items():
            childData = recordFiles.get(child)
            if childData is not None:
                childInfo['cost'] = childData['cost']


def updateEntry(count):
    for entry in entrySet:
        for file, data in recordFiles.items():
            if entry in file:
                entryFiles[file] = {'cost': 0, 'used': 0, 'unused': 0, 'children': {}}
                break

    for entry, entryData in entryFiles.items():
        entryChildren = relationFiles.get(entry)
        if entryChildren is None:
            continue
        for child, relation in entryChildren.items():
            if relation == 'Single':
                entryData['children'][child] = 0
            else:
                entryData['children'][child] = 1
        for child, relation in entryData['children'].items():
            if relation == 0:
                continue
            result = relation
            for parent, _ in entryFiles.items():
                if entry == parent:
                    continue
                parentChildren = relationFiles.get(parent)
                if parentChildren is not None:
                    if child in parentChildren:
                        result += 1
            entryData['children'][child] = result

    for entry, entryData in entryFiles.items():
        cost = 0
        used = 0
        unused = 0
        record = recordFiles.get(entry)
        if record is not None:
            cost += record['data']['cost']
            if record['data']['type'] == 'Used':
                used += record['data']['cost']
            elif record['data']['type'] == 'Unused':
                unused += record['data']['cost']
        for child, c in entryData['children'].items():
            if c <= count:
                childData = recordFiles.get(child)
                if childData is not None:
                    cost += childData['data']['cost']
                    if childData['data']['type'] == 'Used':
                        used += childData['data']['cost']
                    elif childData['data']['type'] == 'Unused':
                        unused += childData['data']['cost']
        entryData['cost'] = cost
        entryData['used'] = used
        entryData['unused'] = unused


def printData(output):
    try:
        os.mkdir(output)
    except Exception as e:
        pass

    with open(Path(output) / 'result_tree', 'w') as f:
        for file, data in recordFiles.items():
            f.write('({}) {} {:.3f}'.format(data['data']['type'], file, data['cost']))
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
                    f.write('    |-> ({}) {} {:.3f}'.format(type, childFile, childData['cost']))
                    f.write('\n')
            else:
                f.write('    |-> (Empty)')
                f.write('\n')
            f.write('\n\n')

    with open(Path(output) / 'result_cost.csv', 'w') as f:
        f.write('Type;File;Cost;Parent;Children')
        f.write('\n')
        for file, data in recordFiles.items():
            f.write('{};{};{:.3f};{};{}'.format(data['data']['type'], file, data['cost'], len(data['parent']), len(data['children'])))
            f.write('\n')

    with open(Path(output) / 'result_entry.csv', 'w') as f:
        f.write('File;Cost;Used;Unused')
        f.write('\n')
        for entry, entryData in entryFiles.items():
            f.write('{};{:.3f};{:.3f};{:.3f}'.format(entry, entryData['cost'], entryData['used'], entryData['unused']))
            f.write('\n')

    with open(Path(output) / 'result_module.csv', 'w') as f:
        f.write('Path;Cost;Used;Unused')
        f.write('\n')
        for module, moduleData in moduleFiles.items():
            if not moduleData['point']:
                continue
            f.write('{};{:.3f};{:.3f};{:.3f}'.format(module, moduleData['cost'], moduleData['used'], moduleData['unused']))
            f.write('\n')


if __name__ == '__main__':
    args = parseArgs()
    parseFile(args.file)
    processData()
    processModuleData(args.point, args.index)
    parseEntry(args.entry)
    processEntryData(args.count)
    printData(args.output)
