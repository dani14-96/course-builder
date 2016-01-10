# Authenticating with ETL #

To use the ETL tool, you will need to provide OAuth2 credentials. There are many ways to do this, described in the [Application Default Credentials documentation](https://developers.google.com/identity/protocols/application-default-credentials). We recommend installing the [Google Cloud SDK](https://cloud.google.com/sdk/) and authenticating with the command

```
gcloud auth login
```

Once this is done, ETL will use your OAuth2 credentials automatically.

You can also set up credentials using the [Google Developer Console](https://console.developers.google.com) if you do not want to install the Google Cloud SDK. Refer to the [Application Default Credentials documentation](https://developers.google.com/identity/protocols/application-default-credentials) for more information.

## I used to sign in with username and password. Can I still do that? ##

Sadly, no. Versions of ETL from Course Builder 1.9 and earlier used [ClientLogin](https://developers.google.com/identity/protocols/AuthForInstalledApps) for authentication, which supported direct authentication to ETL with username and password. ClientLogin is now [deprecated](http://googledevelopers.blogspot.com/2012/04/changes-to-deprecation-policies-and-api.html). Consequently, modern versions of ETL use OAuth2 for authentication, and you must provide credential as above.