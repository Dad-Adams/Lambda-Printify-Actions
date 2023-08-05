import json
import http.client
import boto3
import base64
import datetime
import botocore
import decimal
import pandas as pd

#Constants
#Notes: Product,Print Provider and Desc have potential to be customized in settings
# Potential Issues: Everything is hardcoded to the dev images bucket
S3_BUCKET = 'etsy-automation-webapp-storage-images2238-benedikta'
PRODUCT_ID = "12"
PRINT_PROVIDER_ID = "29"
PRODUCT_DESC = "This classic unisex jersey short sleeve tee fits like a well-loved favorite. Soft cotton and quality print make users fall in love with it over and over again. These t-shirts have-ribbed knit collars to bolster shaping. The shoulders have taping for better fit over time. Dual side seams hold the garment's shape for longer."

#This is the logs of the function that are returned in the body
responseBuilder = {}

###############################################################
def lambda_handler(event, context):
  
  #Show Event
  print("Event: %s" % json.dumps(event))
  
  #Call main function, that returns the status and logs
  status, responseBuilder = DoWork(event, context)

  return {
  'statusCode': status,
  'headers': {
    "Content-Type": "application/json",
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': '*'
    },
  'body': json.dumps(responseBuilder, indent=4),
  #'body':responseBuilder
  }

###############################################################
#Logs function to print to cloudwatch and also add to the json response builder
def LogUpdate(key, value, returnLog= True):

    if returnLog:
        responseBuilder.update({key:value})

    #"value" can be either string or object
    try:
      print(key +  ": " + value)
    except TypeError as e:
      print(key + ": " + json.dumps(value))
    return

###############################################################
def DoWork(event, context):
  
  #Build Logger (sent in response body)
  LogUpdate("Lambda Started", str(datetime.datetime.now()))

  #Load Event Body (sometimes its a string sometimes json, depending on the test)
  payload = None
  try:
      payload = json.loads(event['body'])
  except (TypeError,KeyError) as e: 
      payload = event['body']
  except Exception as e:
      LogUpdate("Event Error", e)
      raise e
  LogUpdate("Payload", payload)

  #Get key value pairs from body
  boss = payload['boss_id']
  LogUpdate("boss_id", boss)
  
  epoch = payload['epoch']
  LogUpdate("epoch", epoch)

  title = payload['title']
  LogUpdate("title", title)

  design_image_title = payload['design_image_title']
  LogUpdate("design_image_title", design_image_title)

  tags = payload['tags']
  LogUpdate("tags", tags)

  #Request Boss data from Dynamo
  dynamodb = boto3.resource('dynamodb')
  table = dynamodb.Table('Bosses')
  item = table.get_item(
      TableName='Bosses',
      Key={
          'BossID': boss,
      },
      AttributesToGet=['PrintifyKey','PrintifyShopID', 'ColorsList', 'PricesIndex']
  )
  
  #LogUpdate("Settings", item['Item'])

  # Get Boss data returned from Dynamo
  printifyKey = item["Item"]["PrintifyKey"]
  LogUpdate("PrintifyKey", printifyKey[:4] + "...")

  shopID = item["Item"]["PrintifyShopID"]
  LogUpdate("PrintifyShopID", shopID[:4] + "...")

  # colorsList = item["Item"]["ColorsList"]
  # LogUpdate("ColorsList Count", len(colorsList))

  pricesIndex = item["Item"]["PricesIndex"]
  LogUpdate("Prices Count", len(pricesIndex))

  colorsList = item["Item"]["ColorsList"]
  LogUpdate("Colors Count", len(colorsList))
  
  #Created Expected Design Key
  designKey = f'public/{boss}/designs/{design_image_title}'
  LogUpdate("Design Key", designKey)
  
  #Try to get design from S3 and check if an error occurs
  s3 = boto3.client('s3')
  try:
    test = s3.head_object(Bucket=S3_BUCKET, Key=designKey)
  except botocore.exceptions.ClientError as e: 
    # The object does not exist.
    if e.response['Error']['Code'] == "404":
        LogUpdate("Design Not Found Error", str(e))
        return 500, responseBuilder  
    else:
        LogUpdate("Design Fetch From S3 Error", e)
        return 500, responseBuilder

  #Get Design from S3
  image_bytes = base64.b64encode(s3.get_object(Bucket=S3_BUCKET, Key=designKey)['Body'].read())

  #Begin Requests ######################################################

  #Upload Design to Printify
  status,response, printifyImageID = Upload_Printify_Image(image_bytes, title, printifyKey)
  LogUpdate("Upload Printify Image Status", status)
  if(status != 200):
    LogUpdate("Upload Printify Image Response", response)
    return 500, responseBuilder
  LogUpdate("Upload Printify ImageID", printifyImageID)

  #Craft Product Body
  status, productBody = Create_Product_Body(colorsList, PRODUCT_ID, PRINT_PROVIDER_ID, pricesIndex, title, printifyImageID, printifyKey)
  LogUpdate("Printify Product Body", productBody)

  #Create Printify Product (from Body)
  status, response, productID = Create_Printify_Product(shopID, productBody, printifyKey)
  LogUpdate("Create Printify Product Status", status)
  if(status != 200):
    LogUpdate("Create Printify Product Response", response)
    return 500, responseBuilder
  LogUpdate("Created Printify ProductID", productID)

  #Publish Product
  status, response = Publish_Printify_Product(shopID,productID, printifyKey)
  LogUpdate("Publish Printify Product Status", status)
  LogUpdate("Publish Printify Product Response", response)
  if(status != 200):
    return 500, responseBuilder
  
  LogUpdate("Lambda Completed", str(datetime.datetime.now()))

  return 200, responseBuilder
##################################################################
def Get_Shop_ID_Request(tempKey):
  #Get Shop ID 
    conn = http.client.HTTPSConnection("api.printify.com")
    payload = ''
    headers = {
      'Authorization': 'Bearer ' + tempKey
    }
    
    conn.request("GET", "/v1/shops.json", payload, headers)
    res = conn.getresponse()
    data = res.read()
    resString = data.decode("utf-8")
    resJson = json.loads(resString)
    
    print("ShopID Response: " + resString)
    print("ShopID " + str(resJson[0]["id"]))

    if(res.status != 200):
        return {
        'statusCode': 201,
        'body': json.dumps('ShopID Fail!')
        }

    return resJson[0]["id"]
#####################################################
#Upload Image to Printify
def Upload_Printify_Image(imageString, filename, apiKey):
  
    conn = http.client.HTTPSConnection("api.printify.com")
    payload = json.dumps({
      "file_name": filename,
      "contents": imageString.decode("utf-")
    })
    headers = {
      'Authorization': 'Bearer ' + apiKey,
      'Content-Type': 'application/json'
    }
    conn.request("POST", "/v1/uploads/images.json", payload, headers)
    res = conn.getresponse()
    data = res.read()
    resString = data.decode("utf-8")
    resJson = json.loads(resString)

    # print("Upload Image Response: " + resString)
    # print("Image ID: " + str(resJson["id"]))
    result = ""
    if(res.status == 200):
      result = str(resJson["id"])

    return res.status, resString, result
##############################################################
#Creates the Product body and configures
def Create_Product_Body(colorsList, productID, ppID, pricesIndex, title, printifyImageID, apiKey):
  #Each Catalog Item in Printify has several variants. A variant is a particular size, color, etc of a product
  #Ex: Item: Bella Canvas 3001 has variants - Size Medium and Color red with ID 123456
  variantsList = []
  variantIDsList = []

  #Get List of all variants for given Catalog Item with given Print Provider
  conn = http.client.HTTPSConnection("api.printify.com")
  payload = ''
  headers = {
    'Authorization': 'Bearer ' + apiKey
  }
  conn.request("GET", f"/v1/catalog/blueprints/{productID}/print_providers/{ppID}/variants.json", payload, headers)
  res = conn.getresponse()
  data = res.read()
  resString = data.decode("utf-8")
  resJson = json.loads(data)
  if(res.status != 200):
    LogUpdate("Get Variants Failed - Status", resString)
    LogUpdate("Get Variants Failed - Response", resString)
    return res.status, {}

  #Get Variants IDs for the users selected colors
  for color in colorsList:
      foundColor = False
      for variant in resJson["variants"]:
          if (variant["options"]["color"].lower() == color.lower()):
              foundColor = True
              #variantsList.append(VariantPlus(variant["id"], variant["options"]["color"], ))
              variantsList.append({"id": variant["id"], "price": int(decimal.Decimal(pricesIndex[variant["options"]["size"]]).quantize(decimal.Decimal('0.01')) * 100), "is_enabled": True})
              variantIDsList.append(variant["id"])
      if(not foundColor):
          LogUpdate("Color not found in variants",color)
  LogUpdate("Variants Count", len(variantsList))
  LogUpdate("VariantIDsList", variantIDsList)

  #Create Payload/Product Body
  payload = {
    "title": "",
    "description": PRODUCT_DESC,
    "blueprint_id": int(productID),
    "print_provider_id": int(ppID),
    "tags": [],
    "variants": variantsList,
    "print_areas": [
      {
        "variant_ids": variantIDsList,
        "placeholders": [
          {
            "position": "front",
            "images": [
              {
                "id": "",
                "x": 0.5,
                "y": 0.5,
                "scale": 0.94,
                "angle": 0
              }
            ]
          }
        ]
      }
    ]
  }

  payload['print_areas'][0]['placeholders'][0]['images'][0]['id'] = printifyImageID
  payload['title'] = title

  return res.status, payload

############################################################
#Create the Product in Printify based on the body, if success return the ID
def Create_Printify_Product(shopID, jsonPayload,tempKey):
  conn = http.client.HTTPSConnection("api.printify.com")
  payload = json.dumps(jsonPayload)
  headers = {
    'Authorization': 'Bearer ' + tempKey,
    'Content-Type': 'application/json'
  }
  conn.request("POST", "/v1/shops/" + str(shopID) + "/products.json", payload, headers)
  res = conn.getresponse()
  data = res.read()
  resString = data.decode("utf-8")
  resJson = json.loads(resString)

  result = ""
  if(res.status == 200):
    result = resJson["id"]

  return res.status, resString, result
####################################################################
#Publish a Printify Product by ID
def Publish_Printify_Product(shopID, productID,tempKey):
  conn = http.client.HTTPSConnection("api.printify.com")
  payload = json.dumps({
    "title": True,
    "description": True,
    "images": True,
    "variants": True,
    "tags": True,
    "keyFeatures": True,
    "shipping_template": True
  })
  headers = {
    'Authorization': 'Bearer ' + tempKey,
    'Content-Type': 'application/json'
  }
  conn.request("POST", "/v1/shops/" + str(shopID) + "/products/" + str(productID) + "/publish.json", payload, headers)
  res = conn.getresponse()
  data = res.read()
  resString = data.decode("utf-8")
  resJson = json.loads(resString)
  
  return res.status, resString
