import os
import sys
import pdb
import numpy as np
import dill as pickle
import subprocess

import pascal_lite as pascal

try:    
    from mpi4py import MPI
    mpi = MPI.COMM_WORLD
    import h5py
except ImportError:
    pass

def run_compute(outputs):
    graph = pascal.ComputationalGraph([x.value for x in outputs])
    sample_input = [x for x in graph.input_values if not isinstance(x.field, int)][0]
    if isinstance(sample_input.field, str):
        mpi_compute(sample_input, outputs, graph)
    else:
        serial_compute(sample_input, outputs, graph)
    return

def get_inputs(x, size):
    if isinstance(x.field, int):
        if x.field:
            shape = x.shape + (size,)
            field = np.random.rand(*shape)
            return field
        else:
            return np.zeros(size)
    elif isinstance(x.field, np.ndarray):
        return x.field
    elif isinstance(x.field, str):
        return mpi_read_field(x.field)
    else:
        raise Exception('unknown input', x.field)

def serial_compute(sample_input, outputs, graph):
    size = sample_input.field.shape[0]
    inputs = lambda x: get_inputs(x, size)
    actual_outputs = graph(inputs)
    for index, output in enumerate(outputs):
        output.value.field = actual_outputs[index]
    return 

def mpi_compute(*mpi_inputs, **kwargs):

    graph_file = os.path.abspath('compute_graph.pkl')
    outputs_file = os.path.abspath('compute_outputs.pkl')
    args = [graph_file, outputs_file]

    with open(graph_file, 'w') as f:
        pickle.dump(mpi_inputs, f)

    # spawn job and wait for result
    worker_file = os.path.join(os.path.abspath(__file__))
    if 'spawn_job' in kwargs:
        returncode = kwargs['spawn_job'](worker_file, args)
    else:
        returncode = subprocess.call(['mpirun', 'python', worker_file] + args)
    if returncode != 0:
        raise Exception('compute process failed')

    with open(outputs_file, 'r') as f:
        compute_outputs = pickle.load(f)
    outputs = mpi_inputs[1]
    index = 0
    for output in outputs:
        if not output.is_distributed:
            output.value.field = compute_outputs[index]
            index += 1
    return 

def mpi_range(size):
    mpi_size = size / mpi.Get_size()
    start = mpi.rank * mpi_size
    end = min(size, start + mpi_size)
    return start, end

def mpi_read_field(field_file):
    handle = h5py.File(field_file, 'r', driver='mpio', comm=mpi)
    field = handle['/field']
    start, end = mpi_range(field.shape[0])
    field = field[start:end].copy()
    handle.close()
    #field = np.loadtxt(field_file)
    return field

def mpi_write_field(field, field_file):
    handle = h5py.File(field_file, 'w', driver='mpio', comm=mpi)
    fieldData = handle.create_dataset('field', shape=field.shape, dtype=field.dtype)
    start, end = mpi_range(field.shape[0])
    fieldData[start:end] = field
    handle.close()
    #np.savetxt(field_file, field)
    return

def mpi_compute_worker(graph_file, outputs_file):
    with open(graph_file, 'r') as f:
        sample_input, outputs, graph = pickle.load(f)
    
    # read the inputs for the graph
    size = mpi_read_field(sample_input.field).shape[0]
    inputs = lambda x: get_inputs(x, size)
    
    # perform the computation
    actual_outputs = graph(inputs)

    # write the outputs in the parent directory for the job
    compute_outputs = []
    for index, output in enumerate(outputs):
        if output.is_distributed:
            parent_dir = os.path.dirname(output.field)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir)
            mpi_write_field(actual_outputs[index], output.field)
        else:
            compute_outputs.append(actual_outputs[index])
    with open(outputs_file, 'w') as f:
        pickle.dump(compute_outputs, f)
    return

if __name__ == '__main__':
    graph_file, outputs_file = sys.argv[1:3]
    mpi_compute_worker(graph_file, outputs_file)
