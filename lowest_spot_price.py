import sys
import boto3 as boto3
import datetime, time
import logging
import operator

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
region_name = 'sa-east-1'
ec2 = boto3.client('ec2', region_name=region_name)
auto_scaling = boto3.client('autoscaling', region_name=region_name)

#algorithm options:  "prioritize-savings" or "prioritize-multiaz"
algorithm = "prioritize-multiaz"
instance_types = ['m3.large' , 'm4.large' , 'r3.large' , 'r4.large' , 'i3.large', 'c3.large' , 'c4.large']
ondemand_prices = [0.19 , 0.159 , 0.35 , 0.28 , 0.286 , 0.163, 0.155]

def check_spot_configuration():
    logging.info("---------Starting new bid analysis----------------")

    auto_scaling_group_name = 'ag_nginx'
    min_price_percentage = float(1.2) #20%

    min_price = 100000000
    current_bid = 0
    current_instance_type = ''
    current_launch_configuration = None

    logging.info("Checking spot prices...")

    asgs = auto_scaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[
            auto_scaling_group_name
        ]
    )

    actual_auto_scaling_group = None

    for asg in asgs['AutoScalingGroups']:
        actual_auto_scaling_group = asg

        lcs = auto_scaling.describe_launch_configurations(
            LaunchConfigurationNames=[
                asg['LaunchConfigurationName']
            ]
        )

        for lc in lcs['LaunchConfigurations']:
            current_bid = float(lc['SpotPrice'])
            current_instance_type = lc['InstanceType']
            current_launch_configuration = lc
    
    price_map = {}
    average_price_map = {}
    min_price_map = {}
    max_price_map = {}
    ondemand_price_map = {}

    cont = 0
    for item in instance_types:
        ondemand_price_map[item] = ondemand_prices[cont]
        cont += 1
    
    instance_type_min_price = instance_types[0]
    for az in asg['AvailabilityZones']:
        for instance_type in instance_types:
            response = ec2.describe_spot_price_history(
                Filters=[
                    {
                        'Name': 'product-description',
                        'Values': [
                            'Linux/UNIX',
                        ]
                    },
                ],
                AvailabilityZone=az,
                DryRun=False,
                StartTime=datetime.datetime.now(),
                EndTime=datetime.datetime.now(),
                InstanceTypes=[
                    instance_type
                ],
                MaxResults=10,
                )

            for spot_price_record in response['SpotPriceHistory']:
                instance_average_price = 0
                average_price_list = []
                if spot_price_record['InstanceType'] in price_map:
                    average_price_list = price_map[spot_price_record['InstanceType']]
                average_price_list.append(round(float(spot_price_record['SpotPrice']), 4))
                price_map[spot_price_record['InstanceType']] = average_price_list
                
    for key in price_map:
        instance_biggest_price = 100000000
        instance_average_price = 0
        sorted_price_map = sorted(price_map[key])
        min_price_map[key] = sorted_price_map[0]
        max_price_map[key] = sorted_price_map[len(sorted_price_map)-1]

        for price in price_map[key]:
            instance_average_price = instance_average_price + float(price)
        instance_average_price = instance_average_price / len(price_map[key])
        average_price_map[key] = round(instance_average_price, 4)

    sorted_average_price_map = sorted(average_price_map.items(), key=operator.itemgetter(1))
    sorted_min_price_map = sorted(min_price_map.items(), key=operator.itemgetter(1))
    sorted_max_price_map = sorted(max_price_map.items(), key=operator.itemgetter(1))
    
    logging.info("---------------Price Map-------------------------")
    for key in price_map:
        logging.info(key + str(price_map[key]))

    logging.info("---------------Sorted Average Price Map----------")
    for item in sorted_average_price_map:
        logging.info(item)

    logging.info("---------------Min Price Map---------------------")
    for item in sorted_min_price_map:
        logging.info(item)

    logging.info("---------------Max Price Map---------------------")
    for item in sorted_max_price_map:
        logging.info(item)

    logging.info("---------------Decision--------------------------")
    logging.info("Algorithm.............: " + algorithm)
    
    if algorithm == "prioritize-multiaz":
        key = sorted_average_price_map[0][0]
        min_price = get_item_from_list(sorted_max_price_map, key)
        instance_type_min_price = key
    else:
        key = sorted_min_price_map[0][0]
        min_price = float(get_item_from_list(sorted_min_price_map, key))
        instance_type_min_price = key

    logging.debug("Picked instance: " + instance_type_min_price + ":" + str(min_price))
    
    limit_min_price = round(min_price * min_price_percentage, 4)

    logging.info("Ondemand price.....:" + str(ondemand_price_map[instance_type_min_price]))
    logging.info("Savings............:" + str((1-round(min_price/ondemand_price_map[instance_type_min_price], 2))*100) + "%")

    if str(limit_min_price) != str(current_bid):
        logging.info("Action.............: Changing Bid Price")
        logging.info("Best instance type.: " + str(instance_type_min_price))
        logging.info("Best spot price....: " + str(min_price))
        logging.info("Old bid price......: " + str(current_bid))
        logging.info("New bid price......: " + str(limit_min_price))
        change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, True)
    else:
        if current_instance_type != instance_type_min_price:
            logging.info("Action.................: Changing Instance type")
            logging.info("Best instance type.: " + str(instance_type_min_price))
            logging.info("Best spot price....: " + str(min_price))
            logging.info("Old instance type......: " + str(current_instance_type))
            logging.info("New instance type......: " + str(instance_type_min_price))
            logging.info("Old bid price..........: " + str(current_bid))
            logging.info("New bid price..........: " + str(limit_min_price))
            change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, True)
        else :
            logging.info("Action................: Nothing to do")
            logging.info("Best instance type.: " + str(instance_type_min_price))
            logging.info("Best spot price....: " + str(min_price))
            logging.info("Current instance type.: " + str(current_instance_type))
            logging.info("Current bid...........: " + str(current_bid))

    logging.info("---------End of bid analysis---------------------")

def change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, is_spot):
    launch_configuration_name = auto_scaling_group_name + '_LC_' + str(datetime.datetime.now()).replace(":", "")
    new_lc = auto_scaling.create_launch_configuration(
        LaunchConfigurationName=launch_configuration_name,
        ImageId=current_launch_configuration['ImageId'],
        KeyName=current_launch_configuration['KeyName'],
        SecurityGroups=current_launch_configuration['SecurityGroups'],
        UserData=current_launch_configuration['UserData'],
        InstanceType=instance_type_min_price,
        BlockDeviceMappings=current_launch_configuration['BlockDeviceMappings'],
        InstanceMonitoring=current_launch_configuration['InstanceMonitoring'],
        SpotPrice=str(limit_min_price),
        EbsOptimized=current_launch_configuration['EbsOptimized'],
        AssociatePublicIpAddress=True,
    )
    new_asg = auto_scaling.update_auto_scaling_group(
        AutoScalingGroupName=actual_auto_scaling_group['AutoScalingGroupName'],
        LaunchConfigurationName=launch_configuration_name,
    )
    auto_scaling.delete_launch_configuration(
        LaunchConfigurationName=current_launch_configuration['LaunchConfigurationName']
    )

def get_item_from_list(some_list, key):
    for item in some_list:
        if item[0] == key:
            return item[1]
    return None

def lambda_handler(event, context):
    check_spot_configuration()

lambda_handler(None, None)