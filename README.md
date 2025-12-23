# Notion-TV

 Python App that checks Notion for new TV Shows in a database and retrieves info for the show

 Duplicate the [TV Tracker Template](https://allaboutduncan.notion.site/112ba329f59a805da992cd5aa028efb3?v=112ba329f59a8168aed8000ce50de6e3)

 ![TV Tracker Example Image](/images/tvshows.png)

This repository helps in managing TV Shows with Notion. Follow the instructions below to clone the repository and install it via Docker CLI or using `docker-compose`.

## Requirements

* [Notion API Key / Custom Integration](https://developers.notion.com/docs/create-a-notion-integration)
* [TMDb API Key](https://www.themoviedb.org/settings/api) - Required for movie support

## Add-Ons

### Pushover
If you'd like to receive notifications when new shows are processed or error details pushed to your mobile device, Pushover is supported.

In the `docker-compose.yaml` file - configure `USE_PUSHOVER=yes` and enter your Token and User Keys in the lines provided.
* [Pushover](https://pushover.net/)

### AWS S3 Bucket for Banner Style Page Covers
 ![Example Banner Image](/images/banner.webp)

If you want the app to generate banner style Notion Page Covers like the image above, you'll need to have an AWS S3 bucket. This will allow the app to upload and store the images in a location where Notion can import them.

In the `docker-compose.yaml` file - configure `USE_AWS=yes` and enter your Access and Secret Keys in the lines provided.

# Installation

## Clone the Repository

First, you need to clone this repository to your local machine.

```bash
git clone https://github.com/allaboutduncan/notion-tv.git
cd notion-tv
```

## Edit the Docker Compose File

For the app to run,  you must edit the `docker-compose.yaml` fle and configure the following environment variables with the appropriate values.

            - USE_AWS=yes/no
            - AWS_ACCESS_KEY_ID=ENTER-YOUR-ACCESS-KEY-HERE
            - AWS_SECRET_ACCESS_KEY=ENTER-YOUR-SECRET-KEY-HERE
            - AWS_BUCKET=bucket-name
            - AWS_REGION=aws-region
            - NOTION_TOKEN=notion_secret
            - NOTION_DATABASE_ID=notion-database-id
            - GoogleAPIKey=Google-Books-API-Key
            - TMDB_API_KEY=your-tmdb-api-key
            - USE_PUSHOVER=yes/no
            - PO_TOKEN=pushover-app-API-key
            - PO_USER=pushover_user_key

## Installation via Docker Compose (CLI)

Use `docker-compose` to install to load the variables in the yaml file needed to run the app:

1. **Ensure you have Docker Compose installed:**

   Docker Compose is typically included with Docker Desktop on Windows and Mac. On Linux, you may need to install it separately.

2. **Navigate to the project directory:**

   ```bash
   cd notion-tv
   ```

3. **Run Docker Compose:**

   ```bash
   docker-compose up -d
   ```

   This command will build and start the services defined in the `docker-compose.yaml` file in detached mode.

## Installation via Docker Compose (Portainer)

Copy the following and edit the environment variables

    version: '3.9'
    services:
        notion-tv:
            image: allaboutduncan/notion-tv:latest
            container_name: notion-tv
            logging:
                options:
                    max-size: 1g
            restart: always
            volumes:
                - '/var/run/docker.sock:/tmp/docker.sock:ro'
            ports:
                - '3331:3331'
            environment:
                - USE_AWS=yes/no
                - AWS_ACCESS_KEY_ID=ENTER-YOUR-ACCESS-KEY-HERE
                - AWS_SECRET_ACCESS_KEY=ENTER-YOUR-SECRET-KEY-HERE
                - AWS_BUCKET=bucket-name
                - AWS_REGION=aws-region
                - NOTION_TOKEN=notion_secret
                - NOTION_DATABASE_ID=notion-database-id
                - GoogleAPIKey=Google-Books-API-Key
                - TMDB_API_KEY=your-tmdb-api-key
                - USE_PUSHOVER=yes/no
                - PO_TOKEN=pushover-app-API-key
                - PO_USER=pushover_user_key

## Using the Application

Once the application is running, you should be able to view the logs or in the console see the status, which should read...
'Next scan scheduled...'

The app will check your Notion database every 60 seconds for new TV shows and movies. To create a new entry:

1. Duplicate the [TV Tracker Template](https://allaboutduncan.notion.site/112ba329f59a805da992cd5aa028efb3?v=112ba329f59a8168aed8000ce50de6e3)
2. Create a new database entry
3. Set the **Type** field to either "TV Serie" or "Movie"
4. Enter the TV Show or Movie name
5. Wait for the data to be populated (when the process runs every 60-seconds)

**For TV Shows:** Data is retrieved from TVMaze API
**For Movies:** Data is retrieved from TMDb API

The app will also run every Sunday night to check for show status changes & new episodes and update all entries if anything has changed.

## Contributing

If you'd like to contribute to this project, please fork the repository and use a feature branch. Pull requests are warmly welcome.

## Notes

This is my first public project and I've been working/running this personally for 9 months. It's by no means perfect, but I'm interested to get feedback, requests, etc at this point and share it in a more usable way.

If you enjoyed this, want to say thanks or want to encourage updates and enhancements, feel free to [!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/allaboutduncan)


## License

This project is licensed under the GNU General Public License. See the LICENSE file for details.
