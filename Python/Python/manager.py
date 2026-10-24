from supabase import create_client
from validation import validate

url= "https://kudofhxrkxlaponhrrjm.supabase.co"
key= "sb_publishable_Pk9Au_p005UZIrm5cjQ7Yw_I31ag2uy"

client= create_client(url, key)


def get_appliances():
    response= client.table("appliances").select("*").execute()
    return response.data


def add_appliance(appliance,power,quantity,minutes):
    validate(appliance,power,quantity,minutes)

    response= client.table("appliances").insert({
        "appliance": appliance,
        "power": power,
        "quantity": quantity,
        "minutes": minutes
    }).execute()

    return response.data


def calculate_energy(power, quantity, minutes):
    return power*quantity*minutes/60000