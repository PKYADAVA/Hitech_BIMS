from django.db import models

# Branch Model
class Branch(models.Model):
    state = models.CharField(max_length=100)
    branch_name = models.CharField(max_length=100)

    def __str__(self):
        return self.branch_name


# Supervisor Model
class Supervisor(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone_no = models.CharField(max_length=15)
    address = models.TextField()

    def __str__(self):
        return self.name


# Broiler Places Model
class BroilerPlace(models.Model):
    supervisor = models.ForeignKey(Supervisor, on_delete=models.CASCADE)
    place_name = models.CharField(max_length=100)

    def __str__(self):
        return self.place_name


# Broiler Farm Model
class BroilerFarm(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    supervisor = models.ForeignKey(Supervisor, on_delete=models.CASCADE)
    broiler_place = models.ForeignKey(BroilerPlace, on_delete=models.CASCADE)
    farm_code = models.CharField(max_length=50)
    farm_name = models.CharField(max_length=100)
    mobile_no = models.CharField(max_length=15)
    block_name = models.CharField(max_length=100)
    address = models.TextField()
    farm_latitude = models.FloatField()
    farm_longitude = models.FloatField()
    farm_type = models.CharField(max_length=50)

    def __str__(self):
        return self.farm_name


# Broiler Batch Model
class BroilerBatch(models.Model):
    broiler_farm = models.ForeignKey(BroilerFarm, on_delete=models.CASCADE)
    batch_name = models.CharField(max_length=50)

    def __str__(self):
        return self.batch_name


# Broiler Disease Model
class BroilerDisease(models.Model):
    disease_code = models.CharField(max_length=50)
    disease_name = models.CharField(max_length=100)
    symptoms = models.TextField()
    diagnosis = models.TextField()
    image = models.ImageField(upload_to='disease_images/', blank=True, null=True)

    def __str__(self):
        return self.disease_name

