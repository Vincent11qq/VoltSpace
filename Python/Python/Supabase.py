from supabase import create_client

url= "https://kudofhxrkxlaponhrrjm.supabase.co"
key="sb_publishable_Pk9Au_p005UZIrm5cjQ7Yw_I31ag2uy"

supabase= create_client(url,key)

profiles= supabase.table("profiles").select("*").execute()
appliances= supabase.table("appliances").select("*").execute()

print("Profiles:", profiles.data)
print("Appliances:", appliances.data)
print("Database check successfully!")