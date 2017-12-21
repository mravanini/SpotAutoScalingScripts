import boto3
import datetime
import logging
import operator

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%d/%m/%Y %H:%M:%S')

region_name = 'us-east-1'

ec2 = boto3.client('ec2', region_name=region_name)
auto_scaling = boto3.client('autoscaling', region_name=region_name)

#algorithm options:  "prioritize-savings" or "prioritize-multiaz"
#todo: se tiver uma az muito louca, ignorar esta AZ e usar somente 2...
#todo: se virar ondemand, matar instancias pra voltar pra spot...
algorithm = "prioritize-multiaz"

#if you are using prioritize-multiaz, might be a good idea to minimize the number of AZs. This might increase your savings.
max_azs = 3

prefered_instance_type = 'c4.large'
instance_types = ['c3.large' , 'c4.large', 'c5.large', 'm3.large' , 'm4.large' , 'r3.large' , 'r4.large' , 'i3.large']
ondemand_prices = [0.105 , 0.10 , 0.085 , 0.133 , 0.10 , 0.166, 0.133, 0.156]

auto_scaling_group_name = 'spot_asg'
min_price_percentage = float(1.2) #20%

min_price = 100000000
current_bid = 100000000
current_instance_type = ''
current_launch_configuration = None

def check_spot_configuration():
    ondemand_price_map = {}
    cont = 0
    for item in instance_types:
        ondemand_price_map[item] = ondemand_prices[cont]
        cont += 1
    
    logging.info("---------Starting new bid analysis----------------")

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
            try:
                current_bid = float(lc['SpotPrice'])
            except:
                current_bid = ondemand_price_map[prefered_instance_type]
            current_instance_type = lc['InstanceType']
            current_launch_configuration = lc
    
    price_map = {}
    average_price_map = {}
    min_price_map = {}
    max_price_map = {}
    
    instance_type_min_price = instance_types[0]
    for az in asg['AvailabilityZones']:
        #logging.info("Parsing AZ: " + az)
        for instance_type in instance_types:
            response = ec2.describe_spot_price_history(
                Filters=[
                    {
                        'Name': 'product-description',
                        'Values': [
                            'Linux/UNIX (Amazon VPC)',
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

            #logging.info(datetime.datetime.now())
            for spot_price_record in response['SpotPriceHistory']:
                #instance_average_price = 0
                price_list = []
                if spot_price_record['InstanceType'] in price_map:
                    price_list = price_map[spot_price_record['InstanceType']]
                #logging.info("Appending price for AZ: " + az + ", instance " + spot_price_record['InstanceType'])
                price_list.append(round(float(spot_price_record['SpotPrice']), 4))
                price_map[spot_price_record['InstanceType']] = price_list
       
    logging.info("---------------Price Map Before Cut-------------------------")
    for key in price_map:
        logging.info(key + str(price_map[key]))       
                
    #remove max prices
    for key in price_map:
        print type(price_map[key])
        sorted_price_map = sorted(price_map[key])
        logging.info('sorted ' + str(sorted_price_map))
        for x in range(0, len(sorted_price_map)-max_azs):
            sorted_price_map.pop(len(sorted_price_map)-1)
            #logging.info("Removed " + str(removed) + ' from ' + key)
            #print('bla')
        price_map[key] = sorted_price_map
        #for price in price_map[key]:
            #logging.info("Price: " + key + " " + str(price))
            
    #exit()
    
    for key in price_map:
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
    sorted_ondemand_price_map = sorted(ondemand_price_map.items(), key=operator.itemgetter(1))
  
    logging.info("---------------OnDemand Price Map----------------")
    for item in sorted_ondemand_price_map:
        logging.info(item)
    
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

    logging.info("OnDemand price........: " + str(ondemand_price_map[instance_type_min_price]))
    logging.info("Savings...............: " + str((1-round(min_price/ondemand_price_map[prefered_instance_type], 2))*100) + "%")

    #ondemand_instancetype = 'c4.large'
    ondemand_instancetype = prefered_instance_type
    ondemand_price = get_item_from_list(sorted_ondemand_price_map, ondemand_instancetype)
    
    if limit_min_price > ondemand_price:
        logging.info("Action................: Turning to On-Demand")
        logging.info("Instance type.........: " + str(ondemand_instancetype))
        logging.info("On-Demand price.......: " + str(ondemand_price))
        change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, ondemand_instancetype, ondemand_price)
    elif str(limit_min_price) != str(current_bid):
        logging.info("Action................: Changing Bid Price")
        logging.info("Best instance type....: " + str(instance_type_min_price))
        logging.info("Best spot price.......: " + str(min_price))
        logging.info("Old bid price.........: " + str(current_bid))
        logging.info("New bid price.........: " + str(limit_min_price))
        change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, ondemand_instancetype, ondemand_price)
    else:
        if current_instance_type != instance_type_min_price:
            logging.info("Action.................: Changing Instance type")
            logging.info("Best instance type.....: " + str(instance_type_min_price))
            logging.info("Best spot price........: " + str(min_price))
            logging.info("Old instance type......: " + str(current_instance_type))
            logging.info("New instance type......: " + str(instance_type_min_price))
            logging.info("Old bid price..........: " + str(current_bid))
            logging.info("New bid price..........: " + str(limit_min_price))
            change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, ondemand_instancetype, ondemand_price)
        else :
            logging.info("Action................: Nothing to do")
            logging.info("Best instance type....: " + str(instance_type_min_price))
            logging.info("Best spot price.......: " + str(min_price))
            logging.info("Current instance type.: " + str(current_instance_type))
            logging.info("Current bid...........: " + str(current_bid))

    logging.info("---------End of bid analysis---------------------")

def change_asg(auto_scaling_group_name, instance_type_min_price, limit_min_price, current_launch_configuration, actual_auto_scaling_group, ondemand_instancetype, ondemand_price):
    launch_configuration_name = auto_scaling_group_name + '_LC_' + str(datetime.datetime.now()).replace(":", "")
    if limit_min_price <= ondemand_price:
        auto_scaling.create_launch_configuration(
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
    else :
        auto_scaling.create_launch_configuration(
        LaunchConfigurationName=launch_configuration_name,
        ImageId=current_launch_configuration['ImageId'],
        KeyName=current_launch_configuration['KeyName'],
        SecurityGroups=current_launch_configuration['SecurityGroups'],
        UserData=current_launch_configuration['UserData'],
        InstanceType=ondemand_instancetype,
        BlockDeviceMappings=current_launch_configuration['BlockDeviceMappings'],
        InstanceMonitoring=current_launch_configuration['InstanceMonitoring'],
        #SpotPrice=str(limit_min_price),
        EbsOptimized=current_launch_configuration['EbsOptimized'],
        AssociatePublicIpAddress=True,
    )
    auto_scaling.update_auto_scaling_group(
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

def get_key_from_list(some_list, index):
    return some_list[index][0]

def lambda_handler(event, context):
    check_spot_configuration()

lambda_handler(None, None)