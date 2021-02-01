import express, { Request } from 'express';

const app = express();
const port: number = parseInt(process.env.PORT ?? '3000');

app.use(express.json());

app.get<Request>('/', (_, res) => {
  console.log('Twitter OAuth');
  res.sendStatus(200);
});

app.listen(port, () => console.log(`Listening on port ${port}!`));