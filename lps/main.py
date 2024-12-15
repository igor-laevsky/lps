from lps.utils.config import load_configuration, logging_config
import sys
import logging.config

load_configuration(sys.argv[1])
logging.config.dictConfig(logging_config())

logger = logging.getLogger('main')

def main():
    print('123')

if __name__ == "__main__":
    main()
