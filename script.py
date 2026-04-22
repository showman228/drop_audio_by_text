from split_by_actors import main as split_by_actors
from main import main as drop_files
from distribute_cuts import main as distribute_cuts


if __name__ == '__main__':
    split_by_actors()
    drop_files()
    distribute_cuts()