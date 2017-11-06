
from datetime import datetime as dt
import logging
import urllib2
import time
import boto3

sleep_time = 5
deregister_time = 20
level_logging = logging.INFO


def enable_logging():

    logging_file_name = dt.now().strftime('/tmp/spot-%m%d%Y.log')

    logging.basicConfig(filename=logging_file_name, level=level_logging, format= '%(asctime)s %(levelname)s %('
                                                                                 'message)s')
    log_msg = 'Logging enabled in file: %s' % (logging_file_name)
    logging.info('==============================================')
    logging.info(log_msg)
    print log_msg

def get_termination_time():

    # fh = open("/tmp/termination_time.txt", "r")
    # termination_time = fh.read().strip()
    # logging.debug ("termination_time from file = " + termination_time)
    # fh.close()
    # 2017-11-05T18:02:00Z

    termination_time = urllib2.urlopen('http://169.254.169.254/latest/meta-data/spot/termination-time').read()

    return termination_time

def get_region_name():
    az_name = urllib2.urlopen('http://169.254.169.254/latest/meta-data/placement/availability-zone').read()
    region_name = az_name[:-1]
    logging.info('region = ' + region_name)
    return region_name


enable_logging()


region_name = get_region_name()
autoscaling = boto3.client('autoscaling', region_name=region_name)
elb = boto3.client('elb', region_name=region_name)


instance_id = urllib2.urlopen('http://169.254.169.254/latest/meta-data/instance-id').read()
logging.debug ('instance id = ' + instance_id)


instances = autoscaling.describe_auto_scaling_instances(InstanceIds=[instance_id,
                                                                     ],
                                                        MaxRecords=1)
auto_scaling_group_name = instances['AutoScalingInstances'][0]['AutoScalingGroupName']

logging.debug ('auto_scaling_group_name = ' + auto_scaling_group_name)

is_desired_capacity_on = False

is_instance_deregistered = False

auto_scaling_groups = None



while True:

    logging.info( 'looping')

    termination_time_env = get_termination_time()

    termination_time = None

    if termination_time_env:
        termination_time = dt.strptime(termination_time_env, '%Y-%m-%dT%H:%M:%SZ')

    if termination_time:

        logging.info( 'termination_time = ' + str(termination_time) )

        if not is_desired_capacity_on:
            logging.info( 'Incrementing desired capacity' )
            # Increment desired

            auto_scaling_groups = autoscaling.describe_auto_scaling_groups(
                AutoScalingGroupNames=[
                    auto_scaling_group_name,
                ],
                MaxRecords=1
            )

            desired_capacity = auto_scaling_groups['AutoScalingGroups'][0]['DesiredCapacity']

            logging.info ('desired capacity = ' + str(desired_capacity))


            try:
                autoscaling.set_desired_capacity(AutoScalingGroupName=auto_scaling_group_name,
                                             DesiredCapacity=desired_capacity + 1)
            except:
                logging.exception('error on graceful-deregistration.py')

            is_desired_capacity_on = True

        logging.info( (termination_time - dt.now()).total_seconds() )

        if (termination_time - dt.now()).total_seconds() < deregister_time and not is_instance_deregistered:

            load_balancer_name = auto_scaling_groups['AutoScalingGroups'][0]['LoadBalancerNames'][0]

            logging.debug ('load balancer name = '+ load_balancer_name)


            # deregister from load balancer
            response = elb.deregister_instances_from_load_balancer(
                LoadBalancerName=load_balancer_name,
                Instances=[
                    {
                        'InstanceId': instance_id
                    },
                ]
            )
            logging.info ('instance ' + instance_id + ' deregistered from load balancer ' + load_balancer_name)

            is_instance_deregistered = True



    time.sleep(sleep_time)


